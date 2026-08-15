"""Entrypoint.

The implementation lives in the `rankbot` package; this stays as the command
everyone already types:

    BOT_TOKEN=... python bot.py
"""

from rankbot.app import run
from rankbot.logging_setup import setup


def main() -> None:
    setup()
    run()


if __name__ == "__main__":
    main()
