import json
import math
import os


CONFIG_FILE = "usr/usr_data/main_control_config.json"
DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA = 6.0
_LEGACY_FIELD = "total_max_emission_current_ma"


def _log(logger, level, message):
    if logger is None:
        return
    log_func = getattr(logger, level, None)
    if log_func:
        log_func(message, tag="Config")
    elif hasattr(logger, "log"):
        logger.log(message, tag="Config")


def _as_limit(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def load_total_max_emission_current(filepath=CONFIG_FILE, logger=None):
    """Load the persisted emission limit, falling back to the default."""
    if not os.path.exists(filepath):
        _log(logger, "info", "No Main Control emission limit file found.")
        return DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA

    try:
        with open(filepath, "r") as file:
            raw_value = json.load(file)
    except Exception as e:
        _log(logger, "error", f"Error loading Main Control emission limit: {e}")
        return DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA

    # Accept the previous one-field object format so existing config files still work.
    if isinstance(raw_value, dict):
        raw_value = raw_value.get(_LEGACY_FIELD)

    limit = _as_limit(raw_value)
    if limit is None:
        _log(logger, "error", "Invalid Total Max Emission Current. Using default value.")
        return DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA

    return limit


def save_total_max_emission_current(value, filepath=CONFIG_FILE, logger=None):
    """Persist the emission limit as a single JSON number."""
    limit = _as_limit(value)
    if limit is None:
        _log(logger, "error", "Invalid Total Max Emission Current. Save skipped.")
        return False

    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)

    try:
        with open(filepath, "w") as file:
            json.dump(limit, file, indent=4)
    except Exception as e:
        _log(logger, "error", f"Error saving Main Control emission limit: {e}")
        return False

    _log(logger, "info", f"Main Control emission limit saved to {filepath}.")
    return True
