FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so this layer is cached between builds
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as a non-root user
RUN useradd --create-home appuser && mkdir -p /app/instance && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# --preload creates DB tables once before workers fork
CMD ["gunicorn", "--preload", "--workers", "3", "--bind", "0.0.0.0:8000", "--timeout", "60", "wsgi:app"]
