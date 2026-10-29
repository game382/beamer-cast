"""Entry point for the packaged app."""
import sys

from beamer.server import run

if __name__ == "__main__":
    run(open_browser="--no-browser" not in sys.argv)
