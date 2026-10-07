"""Logging configuration."""

import logging
import logging.config

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure application logging on stderr at the given level."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": {"format": LOG_FORMAT}},
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "default"},
            },
            "loggers": {
                "app": {"handlers": ["console"], "level": level.upper(), "propagate": False},
            },
        }
    )
