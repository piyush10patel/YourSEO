# Base image ships Python + a preinstalled, dependency-complete Chromium that
# matches our pinned Playwright version — this avoids the usual "headless
# browser in Docker" pain (missing shared libraries, fonts, etc.).
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY app ./app
COPY README.md ./

# Make the `app` package importable regardless of launcher. `uvicorn` adds the
# CWD to sys.path, but `streamlit run <path>` does not — without this the
# Streamlit container fails with "ModuleNotFoundError: No module named 'app'".
ENV PYTHONPATH=/app

# 8000 = FastAPI (uvicorn), 8501 = Streamlit. docker-compose overrides the
# command per service; the default here runs the API.
EXPOSE 8000 8501

# Simple in-image healthcheck for the API service.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health').status==200 else 1)" \
    || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
