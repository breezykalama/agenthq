"""Seed phase only: run the backend with the console e-mail logger captured to a file in the
harness state directory, so the seed step can read the bootstrap admin's verification link.
The file is deleted as soon as seeding finishes. Usage: serve_with_mail_log.py <port> <mail-log>"""

import logging
import sys

import uvicorn

sys.path.insert(0, ".")
handler = logging.FileHandler(sys.argv[2], encoding="utf-8")
handler.setLevel(logging.INFO)
email_logger = logging.getLogger("agenthq.email")
email_logger.setLevel(logging.INFO)
email_logger.addHandler(handler)
uvicorn.run("app.main:app", host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
