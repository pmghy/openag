#!/bin/bash

# Ensure virtual environment is activated
if [[ -z "${VIRTUAL_ENV}" ]] ; then
    echo "Please activate your virtual environment then re-run script"
    exit 0
fi

# Ensure platform info is sourced
if [[ -z "$PLATFORM" ]]; then
	source $PROJECT_ROOT/scripts/get_platform_info.sh > /dev/null 2>&1
fi

# Ensure platform is i2c enabled
if [[ "$IS_I2C_ENABLED" != "true" ]]; then
	echo "Platform is not i2c enabled"
	exit 0
fi

i2cdetect -y -r $DEFAULT_I2C_BUS