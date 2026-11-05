"""PyInstaller entry point — launches the BoneChilling desktop app."""
import multiprocessing
import sys

from bonechiling.desktop.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # safe no-op; guards frozen subprocesses
    sys.exit(main())
