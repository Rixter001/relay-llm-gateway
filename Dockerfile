# Relay container image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1. The spaCy models are the biggest layer (~600 MB) and change rarely, so they come first
#    and stay cached when only the code changes.
COPY requirements-models.txt ./
RUN pip install -r requirements-models.txt

# 2. Python dependencies and the application.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

# Never run as root inside the container.
RUN useradd --create-home --uid 10001 relay
USER 10001

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
