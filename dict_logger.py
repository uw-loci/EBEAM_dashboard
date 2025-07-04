import logging
from datetime import datetime

# global dictionary to track the status of subsystems
status_dict = {
    "pressure": None,
    "safetyOutputDataFlags": None,
    "safetyInputDataFlags": None,
    "temperatures": None,
    "vacuumBits": None
}


""" update the fields """

def update_field(field, value):
    if field in status_dict:
        status_dict[field] = value
    else:
        raise KeyError(f"'{field}' is not a valid key in status dict.")