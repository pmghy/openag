# Import python modules
import logging, time, json, threading

# Import device modes, errors, and variables
from device.utility.mode import Mode
from device.utility.error import Error
from device.utility.variable import Variable

# Import device state manager
from device.state import State

# Import recipe handler
from device.recipe import Recipe

# Import database models
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()
from app.models import State as StateModel


class Device(object):
    """ A state machine that spawns threads to run recipes, read sensors, set 
    actuators, manage control loops, sync data, and manage external events. """

    # Initialize logger
    logger = logging.getLogger(__name__)

    # Initialize device mode and error
    _mode = None
    _error = None

    # Initialize state object, `state` serves as shared memory between threads
    # Note: Thread should be locked whenever writing to `state` object to 
    # avoid memory corruption.
    state = State()

    # Initialize environment state dict
    state.environment = {
        "sensor": {"desired": {}, "reported": {}},
        "actuator": {"desired": {}, "reported": {}},
        "reported_sensor_stats": {
        "individual": {
                "instantaneous": {},
                "average": {}
            },
            "group": {
                "instantaneous": {},
                "average": {}
            }
        }
    }

    # Initialize recipe state dict
    state.recipe = {
        "recipe": None,
        "start_timestamp_minutes": -1,
        "last_update_minute": -1
    }

    # Initialize thread objects
    recipe = Recipe(state)
    peripherals = {}
    controllers = {}


    def __init__(self):
        """ Initializes device. """
        self.mode = Mode.INIT
        self.error = Error.NONE


    @property
    def mode(self):
        """ Gets device mode. """
        return self._mode


    @mode.setter
    def mode(self, value):
        """ Safely updates device mode in state object. """
        self._mode = value
        with threading.Lock():
            self.state.device["mode"] = value


    @property
    def error(self):
        """ Gets device error. """
        return self._error


    @error.setter
    def error(self, value):
        """ Safely updates device error in state object. """
        self._error = value
        with threading.Lock():
            self.state.device["error"] = value


    def commanded_mode(self):
        """ Checks for commanded mode in device state then returns 
            mode or None. """
        if "commanded_mode" in self.state.device:
            return self.state.device["commanded_mode"]
        else:
            return None

    def run(self):
        """ Runs device state machine. """
        while True:
            if self.mode == Mode.INIT:
                self.run_init_mode()
            elif self.mode == Mode.CONFIG:
                self.run_config_mode()
            elif self.mode == Mode.SETUP:
                self.run_setup_mode()
            elif self.mode == Mode.NORMAL:
                self.run_normal_mode()
            elif self.mode == Mode.LOAD:
                self.run_load_mode()
            elif self.mode == Mode.ERROR:
                self.run_error_mode()
            elif self.mode == Mode.RESET:
                self.run_reset_mode()


    def run_init_mode(self):
        """ Runs initialization mode. Loads stored state from database then 
            transitions to CONFIG. """
        self.logger.info("Entered INIT")

        # Load stored state from database
        self.load_state()

        # Transition to CONFIG
        self.mode = Mode.CONFIG


    def run_config_mode(self):
        """ Runs configuration mode. Tries to load config from stored state. 
            If config not in stored state, loads config from local file then
            transitions to SETUP. """
        self.logger.info("Entered CONFIG")

        # Load config from local file if not in stored state
        if self.state.device["config"] == None:
            self.load_config_from_local_file()

        # Transition to SETUP
        self.mode = Mode.SETUP


    def run_setup_mode(self):
        """ Runs setup mode. Creates and spawns recipe, peripheral, and 
            controller threads, waits for all threads to initialize then 
            transitions to NORMAL. """
        self.logger.info("Entered SETUP")

        # Spawn recipe
        self.recipe.spawn()

        # Create and spawn peripherals
        self.create_peripherals()
        self.spawn_peripherals()

        # Create and spawn controllers
        self.create_controllers()
        self.spawn_controllers()

        # Wait for all threads to initialize
        while not self.all_threads_initialized():
            time.sleep(0.2)

        # Load in recipe from file (TEMPORARY)
        self.recipe.commanded_recipe = json.load(open('device/data/recipe.json'))
        self.recipe.commanded_mode = Mode.LOAD

        # Transition to NORMAL
        self.mode = Mode.NORMAL


    def run_normal_mode(self):
        """ Runs normal operation mode. Updates device state summary and 
            stores device state in database, waits for new config command then
            transitions to CONFIG. Transitions to ERROR on error."""
        self.logger.info("Entered NORMAL")

        while True:
            # Update device state summary
            self.update_device_state_summary()

            # Store system state in database
            self.store_state()
            
            # Check for system error
            if self.mode == Mode.ERROR:
                break

            # Update periodically
            time.sleep(1) # seconds


    def run_load_mode(self):
        """ Runs load mode. Stops all threads, loads config into stored state,
            transitions to CONFIG. """
        self.logger.info("Entered LOAD")

        # Stop all threads
        self.stop_all_threads()

        # Load config into stored state
        self.error = Error.NONE

        # Transition to CONFIG
        self.mode = Mode.CONFIG

 
    def run_reset_mode(self):
        """ Runs reset mode. Clears error state then transitions to INIT. """
        self.logger.info("Entered RESET")

        # Clear errors
        self.error = Error.NONE

        # Transition to INIT
        self.mode = Mode.INIT


    def run_error_mode(self):
        """ Runs error mode. Stops all threads, waits for reset signal then 
            transitions to RESET. """
        self.logger.info("Entered ERROR")

        # Stop all threads
        self.stop_all_threads()

        # Wait for reset
        while True:
            if self.mode == Mode.RESET:
                break

            # Update every 100ms
            time.sleep(0.1) # 100ms


    def load_state(self):
        """ Loads stored state from database if it exists. If not, loads
            config from local file. """

        # Load stored state from database if exists
        if StateModel.objects.filter(pk=1).exists():
            stored_state = StateModel.objects.filter(pk=1).first()

            # Load device state
            stored_device_state = json.loads(stored_state.device)
            self.state.device["config"] = stored_device_state["config"]

            # Load recipe state
            stored_recipe_state = json.loads(stored_state.recipe)
            self.recipe.recipe = stored_recipe_state["recipe"]
            self.recipe.duration_minutes = stored_recipe_state["duration_minutes"]
            self.recipe.start_timestamp_minutes = stored_recipe_state["start_timestamp_minutes"]
            self.recipe.last_update_minute = stored_recipe_state["last_update_minute"]
            self.state.recipe["stored_mode"] = stored_recipe_state["mode"]

            # Load peripherals state
            stored_peripherals_state = json.loads(stored_state.peripherals)
            for peripheral_name in stored_peripherals_state:
                if "stored" in stored_peripherals_state[peripheral_name]:
                    self.state.peripherals[peripheral_name] = {}
                    self.state.peripherals[peripheral_name]["stored"] = stored_peripherals_state[peripheral_name]["stored"]

            # Load controllers state
            stored_controllers_state = json.loads(stored_state.controllers)
            for controller_name in stored_controllers_state:
                if "stored" in stored_controllers_state[controller_name]:
                    self.state.controllers[controller_name] = {}
                    self.state.controllers[controller_name]["stored"] = stored_controllers_state[controller_name]["stored"]
        else:
            # Set device state
            self.state.device["config"] = None

            # Set recipe state
            self.recipe.recipe = None


    def store_state(self):
        """ Stores system state in local database. If state does not exist 
            in database, creates it. """

        if not StateModel.objects.filter(pk=1).exists():
            StateModel.objects.create(
                id=1,
                device = json.dumps(self.state.device),
                recipe = json.dumps(self.state.recipe),
                environment = json.dumps(self.state.environment),
                peripherals = json.dumps(self.state.peripherals),
                controllers = json.dumps(self.state.controllers),
            )
        else:
            StateModel.objects.filter(pk=1).update(
                device = json.dumps(self.state.device),
                recipe = json.dumps(self.state.recipe),
                environment = json.dumps(self.state.environment),
                peripherals = json.dumps(self.state.peripherals),
                controllers = json.dumps(self.state.controllers),
            )


    def load_config_from_local_file(self):
        """ Loads config file into device state. """
        self.state.device["config"] = json.load(open('device/data/config.json'))


    def create_peripherals(self):
        """ Creates peripheral objects. """
        config = self.state.device["config"]
        
        if "peripherals" in config:
            for peripheral_name in config["peripherals"]:
                # Get peripheral module and class name
                module_name = "device.peripheral." + config["peripherals"][peripheral_name]["module"]
                class_name = config["peripherals"][peripheral_name]["class"]

                # Import peripheral library
                module_instance= __import__(module_name, fromlist=[class_name])
                class_instance = getattr(module_instance, class_name)

                # Create peripheral objects
                self.peripherals[peripheral_name] = class_instance(peripheral_name, self.state)


    def spawn_peripherals(self):
        """ Spawns peripheral threads. """
        for peripheral_name in self.peripherals:
            self.peripherals[peripheral_name].spawn()


    def create_controllers(self):
        """ Creates controller objects. """
        config = self.state.device["config"]
        
        if "controllers" in config:
            for controller_name in config["controllers"]:
                # Get controller module and class name
                module_name = "device.controller." + config["controllers"][controller_name]["module"]
                class_name = config["controllers"][controller_name]["class"]

                # Import controller library
                module_instance= __import__(module_name, fromlist=[class_name])
                class_instance = getattr(module_instance, class_name)

                # Create controller objects
                self.controllers[controller_name] = class_instance(controller_name, self.state)


    def spawn_controllers(self):
        """ Spawns controller threads. """
        for controller_name in self.controllers:
            self.controllers[controller_name].spawn()


    def all_threads_initialized(self):
        """ Checks that all recipe, peripheral, and controller 
            theads are initialized. """
        if self.state.recipe["mode"] == Mode.INIT:
            return False
        elif not self.all_peripherals_initialized():
            return False
        elif not self.all_controllers_initialized():
            return False
        return True


    def all_peripherals_initialized(self):
        """ Checks that all peripheral threads have transitioned from INIT. """
        for peripheral_name in self.state.peripherals:
            peripheral_state = self.state.peripherals[peripheral_name]
            if peripheral_state["mode"] == Mode.INIT:
                return False
        return True


    def all_controllers_initialized(self):
        """ Checks that all controller threads have transitioned from INIT. """
        for controller_name in self.state.controllers:
            controller_state = self.state.controllers[controller_name]
            if controller_state["mode"] == Mode.INIT:
                return False
        return True


    def stop_all_threads(self):
        """ Stops all threads. """
        # TODO: stop all threads
        pass


    def update_device_state_summary(self, sensors=True, actuators=True, recipe=True, thread_modes=True):
        """ Updates device state summary. """

        summary = ""

        # Create sensor summary
        if sensors:
            summary += "\n    Sensors:"
            summary += self.get_environment_summary(self.state.environment["sensor"])

        # Create actuator summary
        if actuators:
            summary += "\n    Actuators:"
            summary += self.get_environment_summary(self.state.environment["actuator"])

        # Create recipe summary
        if recipe:
            if self.state.recipe["recipe"] == None:
                summary += "\n    Recipe: None"
            else:
                summary += "\n    Recipe:"
                summary += "\n        Name: {}".format(self.state.recipe["recipe"]["name"])
                summary += "\n        Started: {}".format(self.recipe.start_datestring)
                summary += "\n        Progress: {} %".format(self.recipe.percent_complete_string)
                summary += "\n        Time Elapsed: {}".format(self.recipe.time_elapsed_string)
                summary += "\n        Time Remaining: {}".format(self.recipe.time_remaining_string)
                summary += "\n        Current Phase: {}".format(self.recipe.current_phase)
                summary += "\n        Current Cycle: {}".format(self.recipe.current_cycle)
                summary += "\n        Current Environment: {}".format(self.recipe.current_environment_name)
        
        # Create thread modes summary
        if thread_modes:
            summary += "\n    Modes:"
            summary += "\n        Device: {}".format(self.mode)
            summary += "\n        Recipe: {}".format(self.state.recipe["mode"])
            for peripheral_name in self.state.peripherals:
                verbose_name = self.state.device["config"]["peripherals"][peripheral_name]["verbose_name"]
                mode = self.state.peripherals[peripheral_name]["mode"]
                summary += "\n        {}: {}".format(verbose_name, mode)

        # Update summary in shared state
        with threading.Lock():
            self.state.device["summary"] = summary
        
        self.logger.info(summary)


    def get_environment_summary(self, environment):
        """ Gets summary of current reported --> desired value for each variable. """
        summary = ""

        # Log all variables in reported
        for variable in environment["reported"]:
            name = Variable[variable]["name"]
            unit = Variable[variable]["unit"]
            reported = str(environment["reported"][variable])
            if variable in environment["desired"]:
                desired = str(environment["desired"][variable])
            else:
                desired = "None"
            summary += "\n        " + name + " (" + unit + "): " + reported + " --> " + desired

        # Log remaining variables in desired
        for variable in environment["desired"]:
            if variable not in environment["reported"]:
                name = Variable[variable]["name"]
                unit = Variable[variable]["unit"]
                desired = str(environment["desired"][variable])
                reported = "None"
                summary += "\n        " + name + " (" + unit + "): " + reported + " --> " + desired

        # Check for empty log
        if summary == "":
            summary = "\n        None"

        return summary