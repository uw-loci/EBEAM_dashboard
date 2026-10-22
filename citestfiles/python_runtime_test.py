import subprocess
import sys
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

import pytest

from python_runtime import REQUIRED_PYTHON, require_supported_python


ROOT = Path(__file__).resolve().parents[1]
VersionInfo = namedtuple("VersionInfo", "major minor micro releaselevel serial")


def test_environment_pin_matches_runtime_policy():
    assert (ROOT / ".python-version").read_text().strip() == ".".join(
        map(str, REQUIRED_PYTHON)
    )


def test_supported_python_is_accepted():
    with patch("sys.version_info", VersionInfo(3, 11, 17, "final", 0)):
        require_supported_python()


@pytest.mark.parametrize(
    "version",
    [
        VersionInfo(3, 10, 22, "final", 0),
        VersionInfo(3, 11, 9, "final", 0),
        VersionInfo(3, 11, 16, "final", 0),
        VersionInfo(3, 11, 18, "final", 0),
        VersionInfo(3, 12, 15, "final", 0),
        VersionInfo(3, 13, 17, "final", 0),
        VersionInfo(3, 11, 17, "candidate", 1),
    ],
)
def test_unsupported_python_is_rejected(version):
    with patch("sys.version_info", version):
        with pytest.raises(SystemExit, match=r"requires Python 3\.11\.17"):
            require_supported_python()


@pytest.mark.parametrize("entrypoint", ["main.py", "EBEAM_DASHBOARD.spec"])
def test_unsupported_entrypoint_exits_before_gui_or_build_imports(entrypoint):
    # -S disables site-packages so this also proves the rejection needs no
    # installed dashboard dependencies or PyInstaller, and opens no hardware.
    code = (
        "import runpy, sys; from collections import namedtuple; "
        "VersionInfo = namedtuple('VersionInfo', 'major minor micro releaselevel serial'); "
        "sys.version_info = VersionInfo(3, 11, 9, 'final', 0); "
        f"runpy.run_path({entrypoint!r}, run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert "requires Python 3.11.17" in result.stderr
    assert "found 3.11.9" in result.stderr
    assert "README.md" in result.stderr
    assert "Traceback" not in result.stderr
