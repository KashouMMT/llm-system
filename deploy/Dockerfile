# Backend image for llm-system, run in --api mode.
#
# Build context is the repository root (see deploy/docker-compose.yml and
# the .dockerignore there). Local development stays native on Windows —
# nothing here should make `python -m app.main` require Docker.

FROM python:3.14-slim

# PYTHONUNBUFFERED  — logs reach `docker logs` immediately, not on flush.
# PYTHONDONTWRITEBYTECODE — no .pyc in a frequently rebuilt layer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# A container's logs must go to stdout to be visible through `docker logs`
# / CloudWatch. The app still also writes app/logs/*.log; override in
# compose if that is not wanted.
ENV CONSOLE_LOG=true

# WORKDIR is the repository root inside the image: logger.py writes the
# relative path app/logs, LocalFileStorage writes app/generated_files, and
# load_dotenv() reads ./.env — all resolved from here.
WORKDIR /app

# Dependencies in their own layer, so a source-only change does not
# reinstall the (large) langchain / langgraph tree.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Run as a non-root user.
RUN useradd --create-home --uid 1000 app

# Application code only — .dockerignore keeps ui/, .venv/, .git/, docs and
# the generated/log directories out of the context.
COPY app/ ./app/

# Created here so the image does not depend on a volume being mounted over
# them; compose mounts named volumes at these paths anyway.
RUN mkdir -p app/logs app/generated_files \
    && chown -R app:app /app

USER app

EXPOSE 8000

# API_HOST / API_PORT come from the environment (default 0.0.0.0:8000).
CMD ["python", "-m", "app.main", "--api"]
