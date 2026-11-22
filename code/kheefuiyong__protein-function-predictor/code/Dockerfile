FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PFP_MODEL_PATH=/app/models/baseline_logistic.joblib

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

# Install CPU-only PyTorch.
RUN python -m pip install \
    --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.2"

# Install the application and its remaining dependencies.
RUN python -m pip install \
    --no-cache-dir \
    .

COPY models/baseline_logistic.joblib /app/models/baseline_logistic.joblib

EXPOSE 8000

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=60s \
    --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health')"

CMD python -m uvicorn protein_function_predictor.api:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}"
