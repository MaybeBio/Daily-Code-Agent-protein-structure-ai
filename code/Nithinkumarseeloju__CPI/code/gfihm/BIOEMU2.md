# BioEmu-2 in this CPI project

The site can export your exact protein/compound input, import the remote GPU result, and play its predicted time-ordered frames. The existing CPI score models remain the affinity predictors. This integration does not train BioEmu-2. No remote GPU has been connected, and model inference has not been tested from this Windows machine.

## 1. Export a pair from the site

Start the project with `start_cpi.ps1` and open http://127.0.0.1:8765/. Select a Davis, KIBA or Metz row, or enter one protein sequence and one compound SMILES. Open **BioEmu-2 predicted structure and motion** and click **Download GPU input**. The ZIP contains the full sequence, compound, worker script and this guide. The protein is not silently shortened.

The exported `pair.yaml` is JSON-formatted YAML, accepted by BioEmu-2. The worker builds the same system from `request.json` so editing `pair.yaml` will not change the requested pair. To change the inputs, export a new pair from the site.

## 2. Set up a separate Linux GPU environment

In VS Code, connect to your Linux GPU host with Microsoft's Remote - SSH extension. Use the actual host and authentication supplied by your provider. These commands belong in the remote terminal. A GPU host has not been supplied in this project.

```bash
nvidia-smi
python3.12 --version
git clone https://github.com/microsoft/bioemu2.git
cd bioemu2
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install ".[cuda,viz]"
bioemu2 --help
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
git rev-parse HEAD
python -m pip freeze > bioemu2_environment.txt
```

Use this CUDA 13 setup on a compatible GPU/driver, such as the A100 configuration in your instructions. The official project also documents a CUDA 12 installation, and reports testing T4 with that installation. Check the current requirements for your host. Two T4 GPUs do not combine their memory automatically; BioEmu-2's context parallelism requires at least four GPUs. Memory needs depend on the whole molecular system. A large kinase may not fit a particular GPU. No 30-hour completion guarantee applies to these new structure/motion jobs.

Do not install these dependencies into the Windows CPI environment or the existing affinity-training environment. Keep the environment file and commit ID with your results. The first prediction can download weights and query an external MSA service for the protein sequence.

## 3. Predict your pair and its motion

Upload and extract the downloaded input ZIP into a new directory on the GPU host. Keep the BioEmu environment activated, change to the extracted directory, then run:

```bash
python bioemu2_worker.py --request request.json --out run01 --steps 10 --lag-ns 1
```

This predicts one starting complex, then makes ten successive motion steps (eleven frames including time zero). To run a single pose first:

```bash
python bioemu2_worker.py --request request.json --out pose01 --steps 0
```

Use a new output directory for each attempt. The worker saves the starting pose before motion begins. Motion interrupted midway is not resumable by this wrapper; a successful affinity-training checkpoint does not resume a BioEmu job. Read `status.json` for the current stage. If it fails, `error.txt` contains the exact error. No example protein is substituted for your pair.

## 4. Show it in the local site

Download `run01/cpi_bioemu2_result.zip` to Windows. In the site, select the same input pair and use **Import GPU result**. The importer checks input identity, the complete protein residue sequence, compound element counts and bond connectivity, atom indices, finite XYZ values, frame times and per-frame geometry-report lengths. It does not independently establish stereochemistry or biological binding correctness from the coordinates.

Play, pause or scrub the separate BioEmu viewer. Protein is gray, compound gold, and residues within 6 angstrom of the compound are teal. The nearby-residue list updates for each frame. These distances do not assign hydrogen bonds. **Load saved result** reopens the latest imported result for the current pair after a site restart. **Download original result** preserves the full CIF, XTC, physicality report and provenance in a ZIP. Saved results are stored under `processed/bioemu2/results/<pair>/<result>/`.

Frames are model predictions, not experimental observations or a guarantee that the compound will enter the pocket. BioEmu-2's protein geometry checks do not validate ligand chemistry. Failed or unchecked frames remain visible with an explicit label. The viewer preserves frame order and does not convert unrelated samples into a binding animation. The existing experimental/docking viewer still has its own clearly labelled illustrative approach.

## Errors in simple words

| Message | Meaning and next step |
|---|---|
| Needs a Linux GPU machine | This worker cannot run in ordinary Windows Python. Run it on your Linux GPU host. |
| No usable NVIDIA GPU | The remote GPU or driver is not available. Check `nvidia-smi` and the active Python environment. |
| GPU ran out of memory | The protein and compound are too large for the available memory. Use a larger GPU; do not crop the protein without scientific justification. |
| Different protein or compound | The result ZIP belongs to another input. Select the pair that produced it. |
| Complete sequence missing | The output protein is shortened or does not match. The site refuses to mislabel it as your full protein. |
| Geometry check failed | Some predicted atom arrangements look unreasonable. Inspect the flagged frame; it is not proof of a real binding pose. |
| Package/download/MSA error | Read `error.txt`; check the isolated installation and remote internet connection, then retry in a new output folder. |

Official references: [installation](https://github.com/microsoft/bioemu2#installation), [system YAML](https://github.com/microsoft/bioemu2/blob/main/docs/boltz.md), [sampling and geometry checks](https://github.com/microsoft/bioemu2/blob/main/docs/sampling.md), [time-ordered propagation](https://github.com/microsoft/bioemu2/blob/main/docs/propagation.md), [VS Code Remote SSH](https://code.visualstudio.com/docs/remote/ssh).
