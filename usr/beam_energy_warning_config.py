import json
import math
import os


CONFIG_FILE = 'usr/usr_data/beam_energy_warning_limits.json'
POS20KV_SUPPLY_KEY = "pos20kv"

DEFAULT_WARNING_LIMITS = {
    "pos1kv": {
        "min_voltage_v": 0.0,
        "max_voltage_v": 1000.0,
        "max_current_ma": 30.0,
    },
    "neg1kv": {
        "min_voltage_v": 0.0,
        "max_voltage_v": 1000.0,
        "max_current_ma": 30.0,
    },
    "pos20kv": {
        "min_voltage_v": 0.0,
        "max_voltage_v": 20000.0,
        "max_current_ma": 1.0,
    },
    "pos3kv": {
        "min_voltage_v": 0.0,
        "max_voltage_v": 3000.0,
        "max_current_ma": 10.0,
    },
}

LIMIT_FIELDS = ("min_voltage_v", "max_voltage_v", "max_current_ma")


def _copy_defaults():
    return {supply: dict(limits) for supply, limits in DEFAULT_WARNING_LIMITS.items()}


def _log(logger, level, message):
    if logger is None:
        return

    log_func = getattr(logger, level, None)
    if log_func:
        log_func(message, tag="Config")
    elif hasattr(logger, "log"):
        logger.log(message, tag="Config")


def _valid_number(value):
    if isinstance(value, bool):
        return False
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value >= 0


def _max_allowed_value(defaults, field):
    if field == "max_current_ma":
        return defaults[field]
    return defaults["max_voltage_v"]


def normalize_warning_limits(raw_limits, logger=None):
    """Merge user warning-limit data with defaults and discard invalid values."""
    normalized = _copy_defaults()

    if raw_limits is None:
        return normalized

    if not isinstance(raw_limits, dict):
        _log(logger, "error", "Beam Energy warning limits must be a JSON object. Using defaults.")
        return normalized

    for supply_key, defaults in DEFAULT_WARNING_LIMITS.items():
        raw_supply = raw_limits.get(supply_key, {})
        if raw_supply in (None, ""):
            raw_supply = {}
        if not isinstance(raw_supply, dict):
            _log(logger, "error", f"Invalid warning limits for {supply_key}. Using defaults.")
            continue

        candidate = dict(defaults)
        for field in LIMIT_FIELDS:
            if field not in raw_supply:
                continue
            value = raw_supply[field]
            if not _valid_number(value):
                _log(
                    logger,
                    "error",
                    f"Invalid {field} warning limit for {supply_key}. Using default value.",
                )
                continue

            value = float(value)
            max_allowed = _max_allowed_value(defaults, field)
            if value > max_allowed:
                _log(
                    logger,
                    "error",
                    f"{field} warning limit for {supply_key} exceeds {max_allowed:g}. Using default value.",
                )
                continue

            candidate[field] = value

        if candidate["max_voltage_v"] < candidate["min_voltage_v"]:
            _log(
                logger,
                "error",
                f"Invalid voltage warning range for {supply_key}. Using defaults.",
            )
            candidate["min_voltage_v"] = defaults["min_voltage_v"]
            candidate["max_voltage_v"] = defaults["max_voltage_v"]

        normalized[supply_key] = candidate

    return normalized


def load_beam_energy_warning_limits(filepath=CONFIG_FILE, logger=None):
    """Load persisted Beam Energy warning limits, falling back to defaults."""
    if not os.path.exists(filepath):
        _log(logger, "info", "No Beam Energy warning-limit configuration file found.")
        limits = _copy_defaults()
        save_beam_energy_warning_limits(limits, filepath=filepath, logger=logger)
        return limits

    try:
        with open(filepath, "r") as file:
            raw_limits = json.load(file)
    except Exception as e:
        _log(logger, "error", f"Error loading Beam Energy warning limits: {e}")
        return _copy_defaults()

    _log(logger, "debug", f"Beam Energy warning limits loaded from {filepath}.")
    limits = normalize_warning_limits(raw_limits, logger=logger)
    if raw_limits != limits:
        save_beam_energy_warning_limits(limits, filepath=filepath, logger=logger)
    return limits


def save_beam_energy_warning_limits(limits, filepath=CONFIG_FILE, logger=None):
    """Persist Beam Energy warning limits. Returns True on success."""
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    normalized = normalize_warning_limits(limits, logger=logger)

    try:
        with open(filepath, "w") as file:
            json.dump(normalized, file, indent=4)
    except Exception as e:
        _log(logger, "error", f"Error saving Beam Energy warning limits: {e}")
        return False

    _log(logger, "debug", f"Beam Energy warning limits saved to {filepath}.")
    return True
