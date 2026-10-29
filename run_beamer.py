"""Entry point for the packaged app."""
import sys

from beamer.app import main

if __name__ == "__main__":
    main(open_browser="--no-browser" not in sys.argv)
