import logging
import sys
from typing import Any

import structlog

def setup_logging(level: str = "INFO") -> None:
    """Configures structlog with standard formatting.
    
    In development, it will print colorized, user-friendly logs.
    In production (or non-TTY environments), it prints structured JSON logs.
    """
    logging_level = getattr(logging, level.upper(), logging.INFO)
    
    # Base logging configuration
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging_level,
    )
    
    processors: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    
    # If stdout is a TTY, use ConsoleRenderer, else use JSONRenderer
    if sys.stdout.isatty():
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.append(structlog.processors.JSONRenderer())
        
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

setup_logging()
logger = structlog.get_logger("multi-agent-system")
