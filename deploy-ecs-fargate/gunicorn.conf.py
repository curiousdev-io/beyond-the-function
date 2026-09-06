"""gunicorn settings for the container.

Keeping these here rather than as CMD flags means the Dockerfile, `mise run
run`, and anything else all start the server the same way.
"""

import os

from log_config import dict_config, log_level

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

# Fine for 256 CPU units; scale it with the task size.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))

# Both to stdout, where the awslogs driver can see them. Nothing writes to the
# container filesystem.
accesslog = "-"
errorlog = "-"
loglevel = log_level().lower()

logger_class = "gunicorn_logging.JsonAccessLogger"
logconfig_dict = dict_config()
