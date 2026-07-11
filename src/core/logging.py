import logging
import sys
import json

import json
import logging
import sys

# --------- Creating JSON Formatter for Logging  --------- #
# loggin.Formatter is a class that formats log records. We will create a custom formatter that outputs logs in JSON format.


class JSONFormatter(logging.Formatter):
    """Format each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge extra fields (request_id, duration_ms, etc.)
        for key in ("request_id", "method", "path", "status", "duration_ms", "error_code"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

# Setup logging configuration to use JSONFormatter and output to stdout.

def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout) # Create a stream handler that outputs to stdout
    handler.setFormatter(JSONFormatter()) # Set the custom JSON formatter for the handler
    root = logging.getLogger() # Get the root logger
    root.handlers = [handler] # Set the handler for the root logger
    root.setLevel(level) # Set the logging level for the root logger