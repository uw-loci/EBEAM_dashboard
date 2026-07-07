import json
import math
import os


CONFIG_FILE = "usr/usr_data/process_monitor_config.json"
RANGE_FIELDS = (
    "warning_min_c",
    "warning_max_c",
    "display_min_c",
    "display_max_c",
)

DEFAULT_PROCESS_MONITOR_CONFIG = {
    "disabled_sensors": [],
    "sensors": {
        "Solenoid 1": {
            "warning_min_c": -90.0,
            "warning_max_c": 500.0,
            "display_min_c": 10.0,
            "display_max_c": 130.0,
        },
        "Solenoid 2": {
            "warning_min_c": -90.0,
            "warning_max_c": 500.0,
            "display_min_c": 10.0,
            "display_max_c": 130.0,
        },
        "Chamber Top": {
            "warning_min_c": -90.0,
            "warning_max_c": 500.0,
            "display_min_c": 10.0,
            "display_max_c": 100.0,
        },
        "Chamber Bot": {
            "warning_min_c": -90.0,
            "warning_max_c": 500.0,
            "display_min_c": 10.0,
            "display_max_c": 100.0,
        },
        "Air temp": {
            "warning_min_c": -90.0,
            "warning_max_c": 500.0,
            "display_min_c": 10.0,
            "display_max_c": 50.0,
        },
        "Unassigned": {
            "warning_min_c": -90.0,
            "warning_max_c": 500.0,
            "display_min_c": 10.0,
            "display_max_c": 100.0,
        },
    },
}


def _log(logger, level, message):
    if logger is None:
        return

    log_func = getattr(logger, level, None)
    if callable(log_func):
        log_func(message, tag="Config")
    elif hasattr(logger, "log"):
        logger.log(message, tag="Config")


def _copy_defaults():
    return {
        "disabled_sensors": list(DEFAULT_PROCESS_MONITOR_CONFIG["disabled_sensors"]),
        "sensors": {
            sensor: dict(limits)
            for sensor, limits in DEFAULT_PROCESS_MONITOR_CONFIG["sensors"].items()
        },
    }


def _finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def normalize_process_monitor_config(raw_config, logger=None):
    config = _copy_defaults()
    if not isinstance(raw_config, dict):
        if raw_config is not None:
            _log(logger, "error", "Invalid PMON configuration. Using defaults.")
        return config

    disabled_sensors = raw_config.get("disabled_sensors", [])
    if isinstance(disabled_sensors, list):
        known_sensors = set(config["sensors"])
        config["disabled_sensors"] = [
            sensor for sensor in disabled_sensors if sensor in known_sensors
        ]

    raw_sensors = raw_config.get("sensors", {})
    if not isinstance(raw_sensors, dict):
        _log(logger, "error", "Invalid PMON sensor configuration. Using defaults.")
        return config

    for sensor, defaults in config["sensors"].items():
        raw_limits = raw_sensors.get(sensor, {})
        if not isinstance(raw_limits, dict):
            _log(logger, "error", f"Invalid PMON limits for {sensor}. Using defaults.")
            continue

        candidate = dict(defaults)
        for field in RANGE_FIELDS:
            value = _finite_number(raw_limits.get(field))
            if value is not None:
                candidate[field] = value

        if candidate["warning_min_c"] >= candidate["warning_max_c"]:
            _log(logger, "error", f"Invalid PMON warning range for {sensor}. Using defaults.")
            candidate["warning_min_c"] = defaults["warning_min_c"]
            candidate["warning_max_c"] = defaults["warning_max_c"]
        if candidate["display_min_c"] >= candidate["display_max_c"]:
            _log(logger, "error", f"Invalid PMON display range for {sensor}. Using defaults.")
            candidate["display_min_c"] = defaults["display_min_c"]
            candidate["display_max_c"] = defaults["display_max_c"]

        config["sensors"][sensor] = candidate

    return config


def load_process_monitor_config(filepath=CONFIG_FILE, logger=None):
    if not os.path.exists(filepath):
        _log(logger, "info", "No PMON configuration file found. Creating defaults.")
        config = _copy_defaults()
        save_process_monitor_config(config, filepath=filepath, logger=logger)
        return config

    try:
        with open(filepath, "r") as file:
            raw_config = json.load(file)
    except Exception as exc:
        _log(logger, "error", f"Error loading PMON configuration: {exc}")
        return _copy_defaults()

    config = normalize_process_monitor_config(raw_config, logger=logger)
    if raw_config != config:
        save_process_monitor_config(config, filepath=filepath, logger=logger)
    return config


def save_process_monitor_config(config, filepath=CONFIG_FILE, logger=None):
    normalized = normalize_process_monitor_config(config, logger=logger)
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)

    try:
        with open(filepath, "w") as file:
            json.dump(normalized, file, indent=4)
    except Exception as exc:
        _log(logger, "error", f"Error saving PMON configuration: {exc}")
        return False

    return True
