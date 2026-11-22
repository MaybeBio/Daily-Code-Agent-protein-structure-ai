"""Shared Modal setup: the app, the storage Volumes, and the BindCraft2 image.

Every step file (run_design.py, ...) imports `app` and the Volumes from here,
so there is exactly one place to change names or paths.
"""
import modal

# An App groups all our Modal functions together (shows up in the Modal dashboard).
app = modal.App("inceptive")

# A Volume is persistent storage that survives after a function finishes.
# create_if_missing=True makes it the first time it is used.
RUNS_VOLUME_NAME = "inceptive-runs"
runs_volume = modal.Volume.from_name(RUNS_VOLUME_NAME, create_if_missing=True)
weights_volume = modal.Volume.from_name("alphafold2-weights", create_if_missing=True)

# Where each Volume appears inside the running container.
RUNS_DIR = "/runs"        # one subfolder per run: /runs/<run_name>/...
WEIGHTS_DIR = "/weights"  # model weights, downloaded once and reused
OPTIMUS_RUNS_DIR = "/outputs"  # the same runs Volume as Optimus sees it (its OUTPUTS_MOUNT); used for reference structures

# Target structures (.cif/.pdb) you put in inputs/targets/ are copied into the
# design container at start-up, so a new structure never triggers an image rebuild.
LOCAL_TARGETS_DIR = "inputs/targets"   # on your computer
TARGETS_DIR = "/inputs/targets"        # inside the container

# --- BindCraft2 image -------------------------------------------------------
# An Image is the container recipe. This follows bindcraft2/containers/Dockerfile.
# The bindcraft2/ folder is a git submodule (pinned to a specific commit).
BINDCRAFT_PATH = "/opt/bindcraft"

bindcraft_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "build-essential")
    # Copy the submodule into the image. copy=True is needed so the next step can
    # use the files while building. .git is skipped because it is not needed.
    .add_local_dir("bindcraft2", BINDCRAFT_PATH, copy=True, ignore=["**/.git", "docs"])
    # Editable install, because BindCraft2 finds its settings/ folder next to its source.
    .run_commands(f"pip install -e '{BINDCRAFT_PATH}[cuda13]'")
    # From BindCraft2's Dockerfile: tell the system where the pip-installed CUDA
    # libraries are, otherwise JAX silently falls back to the (very slow) CPU.
    .run_commands(
        "python -c \"import nvidia, pathlib; print('\\n'.join(sorted(str(p) for r in nvidia.__path__ "
        "for p in pathlib.Path(r).glob('*/lib'))))\" > /etc/ld.so.conf.d/bindcraft-cuda.conf && ldconfig"
    )
    # Make BindCraft2 keep its AlphaFold weights (5.3 GB) on the weights Volume.
    .env({"BINDCRAFT_WEIGHTS": f"{WEIGHTS_DIR}/bindcraft"})
    # run_design.py imports these at the top, so the container needs them too
    # (Modal only copies the entrypoint file by itself). Keep this line last.
    .pip_install("pyyaml")
    .add_local_python_source("config_loader", "modal_app")
    .add_local_dir(LOCAL_TARGETS_DIR, TARGETS_DIR)
)

# --- RFD4-Proteina image ------------------------------------------------------
# https://github.com/RosettaCommons/RFD4-Proteina (Baker Lab + NVIDIA flow-matching design model).
# Installed from PyPI with the CUDA 13 extras (needed for its fused kernels). Its ~1.7 GB of
# weights come from Hugging Face (nvidia/RFD4-Proteina) and are cached on their own Volume,
# separate from the AlphaFold2 weights, because HF_HOME points there.
rfd4_weights_volume = modal.Volume.from_name("rfd4-weights", create_if_missing=True)
RFD4_HF_HOME = f"{WEIGHTS_DIR}/rfd4_hf"
RFD4_HF_REPO = "nvidia/RFD4-Proteina"

_rfd4_base = (
    modal.Image.debian_slim(python_version="3.12")
    # libxrender1/libxext6/libsm6/libglib2.0-0: Open Babel (a dependency of atomworks) loads its
    # format plugins against these; without libXrender every plugin fails and rfd4-generate crashes on import.
    .apt_install("git", "build-essential", "libxrender1", "libxext6", "libsm6", "libglib2.0-0")
    .pip_install("rfd4-proteina[all-cuda13]", "pyyaml", "zstandard")
    .env({"HF_HOME": RFD4_HF_HOME})
)

# Same rule as the BindCraft2 image: the add_local_* lines must come last.
rfd4_image = (
    _rfd4_base
    .add_local_python_source("config_loader", "modal_app")
    .add_local_dir(LOCAL_TARGETS_DIR, TARGETS_DIR)
)

# --- RFD4-Proteina + AF2 refolding oracle ------------------------------------
# RFD4's reward-guided search and rfd4-evaluate refold designs with an "oracle". The shipped AF2 oracle
# is an Apptainer image, which Modal cannot run. Its worker (run_alphafold2_batch.py) is plain Python
# though, so we rebuild its environment and fake the `apptainer` command (rfd4_oracle/apptainer):
#   * /opt/conda/bin/python = a Python 3.11 venv with the exact packages from RFD4's image
#     (rfd4_oracle/af2_worker_requirements.txt: JAX 0.10.2 + CUDA 13, haiku, TF-CPU, ...)
#   * the patched AlphaFold source (Pallas kernels) lives on the rfd4-weights Volume at AF2_SRC_DIR,
#     and is linked to /app/alphafold at start-up because RFD4 sets PYTHONPATH=/app/alphafold
#   * the AF2 parameters come from the existing alphafold2-weights Volume (see AF2_PARAMS_SRC)
AF2_SRC_DIR = f"{WEIGHTS_DIR}/af2_oracle/alphafold"          # on rfd4_weights_volume
AF2_PARAMS_VOLUME_DIR = "/af2_params_volume"                 # alphafold2-weights Volume mount
AF2_PARAMS_SRC = f"{AF2_PARAMS_VOLUME_DIR}/bindcraft/alphafold"   # params_model_*.npz live here
AF2_MODEL_DIR = "/af2_model"                                  # needs a params/ folder (linked at start-up)
AF2_JAX_CACHE_DIR = "/tmp/af2_jax_cache"
af2_params_volume = weights_volume  # the existing alphafold2-weights Volume

rfd4_af2_image = (
    _rfd4_base
    .pip_install("uv")
    .add_local_file("rfd4_oracle/af2_worker_requirements.txt", "/opt/af2_worker_requirements.txt", copy=True)
    .add_local_file("rfd4_oracle/apptainer", "/usr/local/bin/apptainer", copy=True)
    .run_commands(
        "chmod +x /usr/local/bin/apptainer",
        "uv venv /opt/conda --python 3.11",
        "uv pip install --python /opt/conda/bin/python --no-deps -r /opt/af2_worker_requirements.txt",
    )
    .env({
        "AF2_RUNTIME_BACKEND": "apptainer",     # served by the shim above
        "AF2_IMAGE": "modal-shim",              # required by RFD4 but ignored by the shim
        "AF2_MODEL_DIR": AF2_MODEL_DIR,
        "AF2_JAX_CACHE_DIR": AF2_JAX_CACHE_DIR,
    })
    .add_local_python_source("config_loader", "modal_app")
    .add_local_dir(LOCAL_TARGETS_DIR, TARGETS_DIR)
)

# --- RFD4-Proteina + OpenFold3 / AF3 refolding oracle --------------------------
# The primary oracle (AF2 above stays as a fallback). RFD4's AF3 oracle runs `apptainer run <sif> python
# run_alphafold_batch.py`; the same worker runs OpenFold3 when AF3_MODEL_DIR holds the ported OF3 weights
# (nvidia/RFD4-Proteina, openfold3/weights/). Native AF3 would use the same image with AF3 weights in another folder.
# We cannot run Apptainer, so the image's contents are copied out of its squashfs file at build time:
#   /alphafold3_venv  Python 3.12 venv with alphafold3_open, JAX (CUDA 13), haiku, rdkit, ... (6.8 GB)
#   /hmmer, /app      HMMER binaries and the AlphaFold3 source with its chemical-components data
# Built on Ubuntu 24.04 (like the original image): the venv's compiled code needs that glibc, and its
# `bin/python` is a link to /usr/bin/python3.12.
_RFD4_SNAPSHOTS = f"{RFD4_HF_HOME}/hub/models--nvidia--RFD4-Proteina/snapshots"
OF3_RUNTIME_GLOB = f"{_RFD4_SNAPSHOTS}/*/openfold3/runtime/of3_af3_refolding_env-cuda13.sqsh"
OF3_WEIGHTS_GLOB = f"{_RFD4_SNAPSHOTS}/*/openfold3/weights"
OF3_MODEL_DIR = "/of3_model"                 # linked to the weights folder at start-up (see run_design_rfd4.py)
AF3_JAX_CACHE_DIR = "/tmp/af3_jax_cache"

_UNPACK_OF3_RUNTIME = (
    "set -e; "
    f"SQSH=$(ls {OF3_RUNTIME_GLOB} | head -1); echo unpacking $SQSH; "
    'unsquashfs -f -d /tmp/of3 "$SQSH" alphafold3_venv hmmer app; '
    "mv /tmp/of3/alphafold3_venv /alphafold3_venv; mv /tmp/of3/hmmer /hmmer; mv /tmp/of3/app /app; "
    "rm -rf /tmp/of3; du -sh /alphafold3_venv /hmmer /app"
)

_rfd4_of3_base = (
    modal.Image.from_registry("ubuntu:24.04", add_python="3.12")
    # Same system libraries as _rfd4_base, plus the system Python 3.12 that the venv points at.
    .apt_install("git", "build-essential", "libxrender1", "libxext6", "libsm6", "libglib2.0-0",
                 "squashfs-tools", "python3.12", "libgomp1")
    .pip_install("rfd4-proteina[all-cuda13]", "pyyaml", "zstandard")
    # Copy the oracle runtime out of the squashfs file (reads the rfd4-weights Volume during the build).
    .run_commands(_UNPACK_OF3_RUNTIME, volumes={WEIGHTS_DIR: rfd4_weights_volume})
    .add_local_file("rfd4_oracle/apptainer", "/usr/local/bin/apptainer", copy=True)
    .run_commands("chmod +x /usr/local/bin/apptainer")
    .env({
        "HF_HOME": RFD4_HF_HOME,
        "UV_PROJECT_ENVIRONMENT": "/alphafold3_venv",           # from the original image
        "XLA_FLAGS": "--xla_gpu_enable_triton_gemm=false",      # from the original image
        "XLA_CLIENT_MEM_FRACTION": "0.95",                      # from the original image
        "AF3_IMAGE": "modal-shim",                              # required by RFD4 but ignored by the shim
        "AF3_JAX_CACHE_DIR": AF3_JAX_CACHE_DIR,
    })
)

rfd4_of3_image = (
    _rfd4_of3_base
    .add_local_python_source("config_loader", "modal_app")
    .add_local_dir(LOCAL_TARGETS_DIR, TARGETS_DIR)
)

# --- Bridge image (CPU only) ------------------------------------------------
# Used by run_validation.py to turn BindCraft2's .cif files into the CSV that
# Optimus expects. It reuses Optimus's own designs_from_structures.py (from the
# optimus/ submodule), so the logic is not copied into this repo.
bridge_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("biotite", "gemmi", "pandas", "numpy", "pyyaml")
    .add_local_file("optimus/designs_from_structures.py", "/root/designs_from_structures.py")
    .add_local_file("optimus/StrucTools.py", "/root/StrucTools.py")
    .add_local_file("optimus/validation_core.py", "/root/validation_core.py")   # re-scoring (rescore_validation.py)
    .add_local_python_source("config_loader", "modal_app", "design_table")
)
