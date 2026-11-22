# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

LABEL maintainer="Dr. Roi Castrellon, DDS <roisasha@gmail.com>"
LABEL description="DrNemo Caries Foundry — Autonomous Biophysical Falsification & Discovery Engine"

# Set deterministic environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=42 \
    DEBIAN_FRONTEND=noninteractive

# Install system biophysics dependencies (AutoDock Vina, OpenBabel, C++ runtimes)
RUN apt-get update && apt-get install -y --no-install-recommends \
    autodock-vina \
    openbabel \
    build-essential \
    libgomp1 \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python biophysics and ML stack
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code and structure
COPY . /app/

# Expose Streamlit dashboard port
EXPOSE 8501

# Default command: run biophysical verification suite
CMD ["pytest", "tests/test_foundry.py", "-v"]
