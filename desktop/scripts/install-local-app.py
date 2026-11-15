"""Repository entry point for Suite's reviewed, reversible APP installer."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'suite'))
from localpilot_suite.app_install import main

if __name__ == '__main__':
    main()
