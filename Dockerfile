# ATLAS-Σ API (FastAPI). Synthetic research simulator: no outbound payment connectivity.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 10001 atlas
COPY pyproject.toml README.md requirements-lock.txt ./
COPY src ./src
RUN pip install -r requirements-lock.txt && pip install --no-deps .
COPY results ./results
ENV ATLAS_DATA_DIR=/data ATLAS_RESULTS_DIR=/app/results
RUN mkdir -p /data && chown atlas:atlas /data
USER atlas
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health').status==200 else 1)"
CMD ["uvicorn", "atlas.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
