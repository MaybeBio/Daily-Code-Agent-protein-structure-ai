# Third-Party Notices

The root MIT license applies to original Boltz-DAP contributions. It does not
replace the licenses or attribution requirements of incorporated third-party
code. Model parameters and external databases remain subject to their own terms.

## Boltz

Boltz-DAP integrates with official Boltz v2.2.1, commit
`cb04aeccdd480fd4db707f0bbafde538397fa2ac`. The native patch modifies Boltz model
and data-processing code; it does not redistribute model weights.

Copyright (c) 2024 Jeremy Wohlwend, Gabriele Corso, Saro Passaro.
The complete original MIT notice is preserved in [licenses/Boltz-MIT.txt](https://github.com/coqylight/boltz_dap/blob/HEAD/licenses/Boltz-MIT.txt).

## FastFold

The distributed implementation adapts FastFold communication and initialization
code and uses its module-level sharding approach. FastFold-derived portions
remain under Apache License 2.0, not the root MIT license.

FastFold's license includes: Copyright 2021- HPC-AI Technology Inc.
Its complete license, including its accompanying third-party notices, is
preserved verbatim in [licenses/FastFold-LICENSE.txt](https://github.com/coqylight/boltz_dap/blob/HEAD/licenses/FastFold-LICENSE.txt).

Modified Boltz-DAP files carry prominent modification notices:

- `boltz_distributed/core.py`: standalone PyTorch/NCCL initialization and explicit local CUDA-device binding.
- `boltz_distributed/comm.py`: padded sharding, group-aware transport, host staging, and communication helpers.
- `boltz_distributed/__init__.py`: project-specific distributed exports.
- `boltz_distributed/wrappers.py`: Boltz-specific MSA and Pairformer wrappers.

The source and license review reference is FastFold commit
`eba496808a91bbcd9661cf832349a418b197015f`. No separate root `NOTICE` file was
present at that reference. The reviewed upstream communication and initialization
files contain no additional file-header copyright notices.

The original historical adaptation commit was not recorded. This reference is
not asserted to be the original copied revision; that provenance limitation is
retained explicitly in [licenses/provenance.json](https://github.com/coqylight/boltz_dap/blob/HEAD/licenses/provenance.json).
No earlier attribution or upstream license text has been removed.