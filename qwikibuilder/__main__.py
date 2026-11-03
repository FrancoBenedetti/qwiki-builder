"""
Entry point for executing qwikibuilder as a module: `python3 -m qwikibuilder`.
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
