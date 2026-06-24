import json
import math
import os


CONFIG_FILE = "usr/usr_data/main_control_config.json"
DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA = 6.0
DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S = 30.0
DEFAULT_BEAMS_ESTOP_CURRENT_LIMIT_MA = 0.7
BEAMS_ESTOP_CURRENT_LIMIT_MIN_MA = 0.0
BEAMS_ESTOP_CURRENT_LIMIT_MAX_MA = 1.0
TOTAL_MAX_EMISSION_CURRENT_FIELD = "total_max_emission_current_ma"
VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD = "vtrx_ccs_disable_grace_period_s"
BEAMS_ESTOP_CURRENT_LIMIT_FIELD = "beams_estop_current_limit_ma"

_DEFAULTS = {
    TOTAL_MAX_EMISSION_CURRENT_FIELD: DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA,
    VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD: DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S,
    BEAMS_ESTOP_CURRENT_LIMIT_FIELD: DEFAULT_BEAMS_ESTOP_CURRENT_LIMIT_MA,
}
_FIELD_RANGES = {
    BEAMS_ESTOP_CURRENT_LIMIT_FIELD: (
        BEAMS_ESTOP_CURRENT_LIMIT_MIN_MA,
        BEAMS_ESTOP_CURRENT_LIMIT_MAX_MA,
    ),
}


def _log(logger, level, message):
    if logger is None:
        return
    log_func = getattr(logger, level, None)
    if log_func:
        log_func(message, tag="Config")
    elif hasattr(logger, "log"):
        logger.log(message, tag="Config")


def _as_non_negative_float(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _as_field_value(field, value):
    value = _as_non_negative_float(value)
    if value is None:
        return None

    field_range = _FIELD_RANGES.get(field)
    if field_range is None:
        return value

    minimum, maximum = field_range
    return value if minimum <= value <= maximum else None


def _read_config(filepath, logger=None):
    if not os.path.exists(filepath):
        _log(logger, "info", "No Main Control config file found.")
        return {}, True

    try:
        with open(filepath, "r") as file:
            data = json.load(file)
    except Exception as e:
        _log(logger, "error", f"Error loading Main Control config: {e}")
        return {}, False

    if isinstance(data, dict):
        return dict(data), False

    legacy_total = _as_non_negative_float(data)
    if legacy_total is None:
        return {}, False
    return {TOTAL_MAX_EMISSION_CURRENT_FIELD: legacy_total}, True


def _normalize_config(config, logger=None):
    normalized = dict(config)
    changed = False
    for field, default_value in _DEFAULTS.items():
        value = _as_field_value(field, normalized.get(field))
        if value is None:
            if field in normalized:
                _log(logger, "error", f"Invalid Main Control config value for {field}. Using default value.")
            normalized[field] = default_value
            changed = True
        else:
            normalized[field] = value
    return normalized, changed


def _write_config(config, filepath, logger=None):
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


def _save_field(field, value, filepath=CONFIG_FILE, logger=None):
    value = _as_field_value(field, value)
    if value is None:
        _log(logger, "error", f"Invalid Main Control config value for {field}. Save skipped.")
        return False

    config, _needs_save = _read_config(filepath, logger=logger)
    config, _changed = _normalize_config(config, logger=logger)
    config[field] = value
    return _write_config(config, filepath, logger=logger)


def _load_field(field, filepath=CONFIG_FILE, logger=None):
    config, needs_save = _read_config(filepath, logger=logger)
    config, changed = _normalize_config(config, logger=logger)
    if needs_save or changed:
        _write_config(config, filepath, logger=logger)
    return config[field]


def load_total_max_emission_current(filepath=CONFIG_FILE, logger=None):
    """Load the persisted emission limit, falling back to the default."""
    return _load_field(TOTAL_MAX_EMISSION_CURRENT_FIELD, filepath=filepath, logger=logger)


def save_total_max_emission_current(value, filepath=CONFIG_FILE, logger=None):
    """Persist the emission limit while preserving other Main Control settings."""
    return _save_field(
        TOTAL_MAX_EMISSION_CURRENT_FIELD,
        value,
        filepath=filepath,
        logger=logger,
    )


def load_vtrx_ccs_disable_grace_period_s(filepath=CONFIG_FILE, logger=None):
    """Load the persisted CCS pressure grace period, falling back to the default."""
    return _load_field(VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD, filepath=filepath, logger=logger)


def save_vtrx_ccs_disable_grace_period_s(value, filepath=CONFIG_FILE, logger=None):
    """Persist the CCS pressure grace period while preserving other settings."""
    return _save_field(
        VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD,
        value,
        filepath=filepath,
        logger=logger,
    )


def load_beams_estop_current_limit_ma(filepath=CONFIG_FILE, logger=None):
    """Load the persisted +20kV Beams E-STOP current limit."""
    return _load_field(BEAMS_ESTOP_CURRENT_LIMIT_FIELD, filepath=filepath, logger=logger)


def save_beams_estop_current_limit_ma(value, filepath=CONFIG_FILE, logger=None):
    """Persist the +20kV Beams E-STOP current limit."""
    return _save_field(
        BEAMS_ESTOP_CURRENT_LIMIT_FIELD,
        value,
        filepath=filepath,
        logger=logger,
    )
