"""Structured logging, and Sentry when a DSN is configured."""

import logging
import sys

from . import config

_CONFIGURED = False


def setup() -> logging.Logger:
    """Idempotent: safe to call from both the entrypoint and the tests."""
    global _CONFIGURED
    log = logging.getLogger("rankbot")
    if _CONFIGURED:
        return log

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(config.LOG_LEVEL.upper())

    # httpx logs every single Telegram API call at INFO, which drowns everything.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.Application").setLevel(logging.INFO)

    if config.SENTRY_DSN:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=config.SENTRY_DSN, traces_sample_rate=0.0)
            log.info("Sentry enabled")
        except ImportError:
            log.warning("SENTRY_DSN is set but sentry-sdk isn't installed")

    _CONFIGURED = True
    return log
