# devops-health-check — pinned slim base, non-root runtime
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first for layer caching; install without cache and drop root.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd -m --uid 1000 --user-group --shell /usr/sbin/nologin appuser

COPY --chown=appuser:appuser app.py .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "--access-logfile=-", "app:app"]
