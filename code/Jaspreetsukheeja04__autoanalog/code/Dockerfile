FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    openbabel \
    libxrender1 libxext6 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /pipeline

COPY requirements.txt .

RUN pip install --no-cache-dir \
    --timeout 300 \
    --retries 5 \
    streamlit pandas numpy matplotlib \
    requests reportlab Pillow pyyaml \
    scikit-learn

RUN pip install --no-cache-dir \
    --timeout 300 \
    --retries 5 \
    rdkit

RUN pip install --no-cache-dir \
    --timeout 600 \
    --retries 5 \
    torch --index-url \
    https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    --timeout 300 \
    --retries 5 \
    transformers biopython \
    chembl-webresource-client snakemake

COPY . .

RUN mkdir -p \
    results/structure results/literature \
    results/analogues results/models \
    results/admet results/screening \
    results/docking results/md \
    results/ranking results/report logs

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0"]
