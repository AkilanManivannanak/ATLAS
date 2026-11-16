# ATLAS-Σ interactive app (Streamlit). Simulated settlement only: no outbound payment connectivity.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 10001 atlas
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY streamlit_app.py pyproject.toml README.md DECISIONS.md ./
COPY .streamlit ./.streamlit
COPY src ./src
COPY results ./results
COPY docs ./docs
COPY data ./data
USER atlas
EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health').status==200 else 1)"
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
