from utils import WebMonitorLogger
from datetime import datetime
import os

webMonitorDir = os.path.join(os.path.dirname(__file__), "EBEAM-Dashboard-Logs")
os.makedirs(webMonitorDir, exist_ok=True)

log_filename = f"webmonitor_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
web_log_path = os.path.join(webMonitorDir, log_filename)

web_monitor_logger = WebMonitorLogger(web_log_path)


# global dictionary to track the status of subsystems
status_dict = {
    "pressure": None,
    "safetyOutputDataFlags": None,
    "safetyInputDataFlags": None,
    "temperatures": None,
    "vacuumBits": None
}


""" update the fields and log full status"""
def update_field(field, value):
    if field in status_dict:
        status_dict[field] = value
        web_monitor_logger.log_dict_update(status_dict)
    else:
        raise KeyError(f"'{field}' is not a valid key in status dict.")