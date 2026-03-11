import logging
import structlog


def configure_logging(level: str = 'INFO') -> None:
    logging.basicConfig(format='%(message)s', level=level.upper())
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt='iso'),
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = 'hastlefam'):
    return structlog.get_logger(name)
