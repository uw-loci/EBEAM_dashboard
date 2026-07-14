"""BCON (Beam Controller) driver package — Modbus RTU."""

from .bcon_driver import (
    BCONDriver,
    BCONMode,
    BCONState,
    MODE_LABEL_TO_CODE,
    MODE_CODE_TO_LABEL,
    STATE_LABELS,
    scan_serial_ports,
    # Register map constants
    TOTAL_REGS,
    REG_WATCHDOG_MS,
    REG_TELEMETRY_MS,
    REG_COMMAND,
    CH_BASE,
    CH_MODE_OFF,
    CH_PULSE_MS_OFF,
    CH_COUNT_OFF,
    CH_ENABLE_TOGGLE_OFF,
    REG_SYS_STATE,
    REG_SYS_REASON,
    REG_FAULT_LATCHED,
    REG_INTERLOCK_OK,
    REG_WATCHDOG_OK,
    REG_LAST_ERROR,
    REG_CH_STATUS_BASE,
    REG_CH_STATUS_STRIDE,
)

__all__ = [
    'BCONDriver',
    'BCONMode',
    'BCONState',
    'MODE_LABEL_TO_CODE',
    'MODE_CODE_TO_LABEL',
    'STATE_LABELS',
    'scan_serial_ports',
]
