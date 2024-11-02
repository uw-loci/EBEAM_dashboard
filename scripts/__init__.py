# __init__.py
from .g9_driver import G9Driver
from .errorTests import TestG9Driver

from .g9_driver import G9Driver  # Updated relative import

# Running the tests (create scriptsG9Drivertestrun_tests.py)
import unittest
from errorTests import TestG9Driver

if __name__ == '__main__':
    unittest.main()