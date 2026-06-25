import logging
import os
from datetime import datetime


def setup_logger(name: str = "stock_notifier") -> logging.Logger:
    logs_dir = "logs"
    os.makedirs(logs_dir, exist_ok=True)

    log_file = os.path.join(
        logs_dir, f"stock_notifier_{datetime.now().strftime('%Y%m%d')}.log"
    )

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        import sys
        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setFormatter(fmt)
        # Ensure stdout accepts UTF-8 on Windows
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        logger.addHandler(fh)
        logger.addHandler(ch)

    return logger
