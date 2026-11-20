FROM python:3.15.2-slim

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Copy dependency specification first (better layer caching)
COPY pyproject.toml uv.lock ./

# Install the locked runtime dependencies into /opt/venv with uv, so the image
# gets exactly the versions in uv.lock (the tested local environment).
# - uv comes from PyPI like every other package, in its latest version. The
#   package versions come from uv.lock, so they do not change with uv itself.
# - --no-dev leaves out the dev group (ADK evaluation tools): evals run
#   locally, not on Cloud Run.
# - --frozen fails the build if uv.lock is out of date with pyproject.toml.
# - uv is only needed here, so it is removed again in the same layer.
RUN /usr/local/bin/python -m pip install --no-cache-dir uv \
 && uv sync --frozen --no-dev --no-install-project \
 && /usr/local/bin/python -m pip uninstall -y uv

# Copy application source
COPY agentic_ai_main.py ./
COPY app/ ./app/

# Expose the port Cloud Run will route traffic to
EXPOSE 8080

# Cloud Run sets PORT=8080 by default.
# Use a production-grade uvicorn invocation (no reload).
CMD ["python", "-m", "uvicorn", "agentic_ai_main:app", "--host", "0.0.0.0", "--port", "8080"]
