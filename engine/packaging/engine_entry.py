"""Entry point for the bundled engine executable (PyInstaller): salvage-engine <command> ..."""
import sys

from salvage.cli import main

if __name__ == "__main__":
    sys.exit(main())
