import json
import math
import os


CONFIG_FILE = "usr/usr_data/main_control_config.json"
DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA = 6.0
DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S = 30.0
TOTAL_MAX_EMISSION_CURRENT_FIELD = "total_max_emission_current_ma"
VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD = "vtrx_ccs_disable_grace_period_s"


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


def _load_raw_config(filepath, logger=None):
    if not os.path.exists(filepath):
        _log(logger, "info", "No Main Control config file found.")
        return None

    try:
        with open(filepath, "r") as file:
            return json.load(file)
    except Exception as e:
        _log(logger, "error", f"Error loading Main Control config: {e}")
        return None


def _config_object_from_raw(raw_value):
    config = {}
    if isinstance(raw_value, dict):
        config.update(raw_value)
    else:
        total_limit = _as_limit(raw_value)
        if total_limit is not None:
            config[TOTAL_MAX_EMISSION_CURRENT_FIELD] = total_limit
    return config


def _load_config_object_for_save(filepath, logger=None):
    raw_value = _load_raw_config(filepath, logger=logger)
    config = _config_object_from_raw(raw_value)

    if _as_limit(config.get(TOTAL_MAX_EMISSION_CURRENT_FIELD)) is None:
        config[TOTAL_MAX_EMISSION_CURRENT_FIELD] = DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA
    if _as_limit(config.get(VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD)) is None:
        config[VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD] = DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S
    return config


def _save_config_object(config, filepath, logger=None):
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)

    try:
        with open(filepath, "w") as file:
            json.dump(config, file, indent=4)
    except Exception as e:
        _log(logger, "error", f"Error saving Main Control config: {e}")
        return False

    _log(logger, "debug", f"Main Control config saved to {filepath}.")
    return True


def load_total_max_emission_current(filepath=CONFIG_FILE, logger=None):
    """Load the persisted emission limit, falling back to the default."""
    raw_value = _load_raw_config(filepath, logger=logger)
    if raw_value is None:
        return DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA

    raw_limit = (
        raw_value.get(TOTAL_MAX_EMISSION_CURRENT_FIELD)
        if isinstance(raw_value, dict)
        else raw_value
    )
    limit = _as_limit(raw_limit)
    if limit is None:
        _log(logger, "error", "Invalid Total Max Emission Current. Using default value.")
        return DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA

    return limit


def save_total_max_emission_current(value, filepath=CONFIG_FILE, logger=None):
    """Persist the emission limit while preserving other Main Control settings."""
    limit = _as_limit(value)
    if limit is None:
        _log(logger, "error", "Invalid Total Max Emission Current. Save skipped.")
        return False

    config = _load_config_object_for_save(filepath, logger=logger)
    config[TOTAL_MAX_EMISSION_CURRENT_FIELD] = limit
    return _save_config_object(config, filepath, logger=logger)


def load_vtrx_ccs_disable_grace_period_s(filepath=CONFIG_FILE, logger=None):
    """Load the persisted CCS pressure grace period, falling back to the default."""
    raw_value = _load_raw_config(filepath, logger=logger)
    if raw_value is None:
        return DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S

    if not isinstance(raw_value, dict) or VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD not in raw_value:
        return DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S

    duration_s = _as_limit(raw_value.get(VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD))
    if duration_s is None:
        _log(logger, "error", "Invalid VTRX CCS disable grace period. Using default value.")
        return DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S

    return duration_s


def save_vtrx_ccs_disable_grace_period_s(value, filepath=CONFIG_FILE, logger=None):
    """Persist the CCS pressure grace period while preserving other settings."""
    duration_s = _as_limit(value)
    if duration_s is None:
        _log(logger, "error", "Invalid VTRX CCS disable grace period. Save skipped.")
        return False

    config = _load_config_object_for_save(filepath, logger=logger)
    config[VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD] = duration_s
    return _save_config_object(config, filepath, logger=logger)
