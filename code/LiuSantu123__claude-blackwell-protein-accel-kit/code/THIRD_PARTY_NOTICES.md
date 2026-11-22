# Third-party notices

This release aggregates the original Anthropic uplifting kits and their pinned
upstream projects. Each kit keeps its own `LICENSE`, `STOCK.md`, and
`third_party_licenses/` directory. Those files govern the corresponding
source and stock snapshot.

The shared runtime is under `kits/common/opt_core/` and retains its Apache 2.0
license and notices. The sm120 exact LayerNorm cubin is included only as a
manifested build artifact; it is not a model weight.

Do not redistribute model checkpoints or databases from a local installation
with this repository. Verify upstream terms before publishing a container or
prebuilt wheel.

The ESMFold2 overlay imports the user's upstream `esm` installation and the
shared `opt_core` runtime. Its implementation was informed by Anthropic's
`big` route; the overlay does not bundle upstream ESMFold2 code or checkpoints.
