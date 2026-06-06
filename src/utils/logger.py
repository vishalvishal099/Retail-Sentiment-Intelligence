"""
Retail Sentiment Intelligence — Structured Logging
Uses structlog if available, falls back to stdlib logging.
"""

import sys
import logging


def setup_logging(level: str = "INFO"):
    """Configure logging."""
    try:
        import structlog
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer() if sys.stderr.isatty() else structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(structlog.get_level_from_name(level)),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )
    except ImportError:
        logging.basicConfig(
            level=getattr(logging, level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )


def get_logger(name: str):
    """Get a named logger instance."""
    try:
        import structlog
        return structlog.get_logger(name)
    except ImportError:
        return _StdlibWrapper(logging.getLogger(name))


class _StdlibWrapper:
    """Wraps stdlib logger to accept structlog-style kwargs."""

    def __init__(self, logger):
        self._logger = logger

    def _format(self, msg, kwargs):
        if kwargs:
            extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"{msg} [{extra}]"
        return msg

    def info(self, msg, *args, **kwargs):
        self._logger.info(self._format(msg, kwargs), *args)

    def warning(self, msg, *args, **kwargs):
        self._logger.warning(self._format(msg, kwargs), *args)

    def error(self, msg, *args, **kwargs):
        self._logger.error(self._format(msg, kwargs), *args)

    def debug(self, msg, *args, **kwargs):
        self._logger.debug(self._format(msg, kwargs), *args)
