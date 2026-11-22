# syntax=docker/dockerfile:1.7
# The native-unit study (scripts/units_atlas.py) on one GPU machine, a GH200's aarch64 or x86_64. The build context is
# the `tree/` of a directory `ws remote run` shipped with the GH200 suite's locks included, so every package the study
# installs is at the version that environment records. From the shipped tree/projects/representation/plm_interpretability:
#   sudo docker build -t tap-probing -f Dockerfile ../../..
# CUDA 13.0 (cu130, lock.txt) needs driver 580 or newer. A 570 driver (CUDA 12.8 at most) builds with
#   --build-arg CUDA_IMAGE=nvidia/cuda:12.6.3-cudnn-devel-ubuntu24.04 --build-arg TORCH_INDEX=cu126 --build-arg LOCK=lock_cu126.txt
# XGBoost's wheel needs CUDA 13 for the GPU, so on such a machine E11's device check stops its pilot.
# At run time scripts/in_container.sh mounts the shipped directory at /workspace, read-only.

ARG CUDA_IMAGE=nvidia/cuda:13.0.1-cudnn-devel-ubuntu24.04
FROM ${CUDA_IMAGE}
ARG TORCH_INDEX=cu130
ARG LOCK=lock.txt

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/opt/venv/bin:/usr/local/bin:$PATH \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/cache/huggingface \
    HF_XET_HIGH_PERFORMANCE=1

# git fetches InterPLM at the commit the requirements pin.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git \
        python3.12 python3.12-dev python3.12-venv && \
    python3.12 -m venv /opt/venv && \
    ln -sf /opt/venv/bin/python /usr/local/bin/python && \
    ln -sf /opt/venv/bin/pip /usr/local/bin/pip

# MMseqs2 18-8cc5c's CPU build, the release the workspace pins, for the missing-annotation search (`missing` stage).
RUN if [ "$(uname -m)" = aarch64 ]; then build=mmseqs-linux-arm64; else build=mmseqs-linux-avx2; fi && \
    curl -fsSL "https://github.com/soedinglab/MMseqs2/releases/download/18-8cc5c/${build}.tar.gz" | tar xz -C /opt && \
    ln -s /opt/mmseqs/bin/mmseqs /usr/local/bin/mmseqs && \
    mmseqs version

COPY projects/representation/plm_interpretability/requirements.txt /tmp/requirements.txt
COPY environments/gh200_suite/${LOCK} /tmp/constraints.txt
# psutil is foundry.pilot's; the rest are the project's declarations, held to the suite's lock where it names them.
RUN pip install --upgrade "pip>=26.2.2" setuptools && \
    pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/${TORCH_INDEX} && \
    pip install -r /tmp/requirements.txt psutil -c /tmp/constraints.txt && \
    python -c "import interplm, torch, transformers, xgboost; print('torch', torch.__version__, 'cuda', torch.version.cuda, 'transformers', transformers.__version__, 'xgboost', xgboost.__version__)"

# InterPLM's setup.py keeps only directories with an __init__.py, and at the pinned commit several have none
# (`interplm.train`, `interplm.data_processing`), so the installed package lacks modules that `interplm.sae.inference`
# and E1's F1 functions import, and the SAE configs in `sae/migration` (found 2026-11-07). The source package of the
# commit pip installed is copied over the install without replacing a file, so every directory imports as in InterPLM's
# own checkout.
RUN commit=$(python -c "import importlib.metadata, json; print(json.loads(importlib.metadata.distribution('interplm').read_text('direct_url.json'))['vcs_info']['commit_id'])") && \
    git clone --quiet https://github.com/ElanaPearl/InterPLM.git /tmp/interplm && \
    git -C /tmp/interplm checkout --quiet "$commit" && \
    site=$(python -c "import interplm, os; print(os.path.dirname(interplm.__file__))") && \
    cp -rn /tmp/interplm/interplm/. "$site/" && \
    rm -rf /tmp/interplm && \
    python -c "import interplm.sae.inference, interplm.analysis.concepts.calculate_f1, interplm.analysis.concepts.compare_activations, interplm.analysis.concepts.report_metrics"

WORKDIR /workspace
CMD ["bash"]
