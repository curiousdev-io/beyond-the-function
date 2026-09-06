# Build for the architecture the task definition asks for. With
# CpuArchitecture: ARM64 in the template, that means:
#
#   docker buildx build --platform linux/arm64 -t <repo>:latest --push .
#
# Building on an x86 laptop and pushing without --platform is the classic way
# to get a task that dies immediately with an exec format error.
FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Dependencies first so a code change does not invalidate the layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py log_config.py gunicorn_logging.py gunicorn.conf.py ./

# Fargate does not give you a host to log into, but that is no reason to run
# as root inside the container.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080

# Bind address, worker count, and JSON logging all live in gunicorn.conf.py, so
# the container and `mise run run-local` start the server identically. The
# config reads PORT itself, which is also why this no longer needs a shell to
# expand it -- exec form means gunicorn is PID 1 and gets SIGTERM directly, so
# ECS task draining works instead of waiting out the stop timeout.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
