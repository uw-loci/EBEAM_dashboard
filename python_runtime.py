"""Python version policy shared by dashboard startup and executable builds."""

import sys


# Keep in sync with .python-version; checked by the runtime policy tests.
# A constant also works inside PyInstaller bundles without an external file.
REQUIRED_PYTHON = (3, 11, 17)


def require_supported_python():
    """Stop before loading dashboard dependencies on an unsupported runtime."""
    if sys.version_info[:3] != REQUIRED_PYTHON or sys.version_info.releaselevel != "final":
        required = ".".join(map(str, REQUIRED_PYTHON))
        current = ".".join(map(str, sys.version_info[:3]))
        raise SystemExit(
            f"EBEAM Dashboard requires Python {required} (final); found {current} "
            f"({sys.version_info.releaselevel}). "
            "Recreate and activate .venv with the pinned Python version as described "
            "in README.md."
        )


if __name__ == "__main__":
    require_supported_python()
