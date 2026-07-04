import logging
import logging.handlers
import os
from datetime import datetime

class Logger:
    """
    Centralized logging for the Flight Meet Agent.
    Logs to both console and data/activity.log.
    """
    _logger = None

    @classmethod
    def get_logger(cls):
        if cls._logger is None:
            # Ensure data directory exists
            os.makedirs("data", exist_ok=True)
            
            logger = logging.getLogger("flight_meet_agent")
            logger.setLevel(logging.INFO)
            
            # Prevent adding handlers multiple times
            if not logger.handlers:
                # File Handler with rotation (5 MB max, keep 3 backups)
                file_handler = logging.handlers.RotatingFileHandler(
                    os.path.join("data", "activity.log"),
                    encoding='utf-8',
                    maxBytes=5 * 1024 * 1024,  # 5 MB
                    backupCount=3,
                )
                file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                file_handler.setFormatter(file_formatter)
                logger.addHandler(file_handler)
                
                # Console Handler
                console_handler = logging.StreamHandler()
                console_formatter = logging.Formatter('%(message)s')
                console_handler.setFormatter(console_formatter)
                logger.addHandler(console_handler)
            
            cls._logger = logger
        return cls._logger

def log_info(message: str):
    Logger.get_logger().info(message)

def log_error(message: str):
    Logger.get_logger().error(message)

def log_warning(message: str):
    Logger.get_logger().warning(message)

def get_recent_logs(n: int = 20) -> str:
    """Returns the last n lines of the activity log."""
    log_path = os.path.join("data", "activity.log")
    if not os.path.exists(log_path):
        return "No logs found."
    
    try:
        with open(log_path, "r", encoding='utf-8') as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception as e:
        return f"Error reading logs: {e}"
