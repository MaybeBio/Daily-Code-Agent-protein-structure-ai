

## Recent Development Activity

The LAMMPS development project continues to evolve rapidly, with significant commits and activity in December 2025. Below is a synthesis of the most impactful recent changes affecting developers and users.

### Transparency Support in Visualization

The most notable recent enhancement is the addition of transparency support to the `dump image` command. A series of commits between December 18-19, 2025, led by [Axel Kohlmeyer](https://github.com/lammps/lammps/commit/f3137c521d76ca6c213388cef9134af7265c1c71), implemented opacity rendering for atoms, bonds, boxes, subboxes, axes, regions, and graphics objects from fixes.

This development directly addresses [feature request #4813](https://github.com/lammps/lammps/issues/4813), where users noted that rendering large global objects like regions or walls could obscure atoms of interest. The implementation uses a dithering algorithm via the Bayer matrix approach, with recommendations for FSAA values of 0.25, 0.5, or 0.75 as documented in [commit 59d391e](https://github.com/lammps/lammps/commit/59d391eee7e8097eb39c9d31a631f616d0f615f4).

The changes were merged through [pull request #4812](https://github.com/lammps/lammps/commit/c4e55dc01d1feca901bb7ae52082194b6b137ce6), which also added a dedicated graphics objects fix. This is a practical improvement for researchers who need to visualize complex systems where transparency helps distinguish overlapping structures.

### Collected Small Fixes and Updates

Alongside the transparency feature, [commit a51f9ba](https://github.com/lammps/lammps/commit/a51f9ba0e719be544293987bb3cbd9939f1b01ee) merged a collection of small fixes. These included:

- Documentation clarification for the `fix align-self` command via [PR #80](https://github.com/lammps/lammps/commit/5e14b2de6f466df7b0bfc3aa898161abe6396d50), contributed by Jeremy FERSULA
- Removal of the deprecated `zcylinder` option from `fix wall/gran` [commit 9d36d64](https://github.com/lammps/lammps/commit/9d36d6436e077035c5254d80b013c967d2f46e22)
- Various typo corrections and code cleanup

These incremental fixes may seem minor individually, but they collectively improve code quality and user experience. The documentation corrections, in particular, address a common pain point where unclear documentation leads to incorrect simulation setups.

## Recent Bug Fixes and Resolutions

Several important bugs were resolved in recent activity, addressing issues that affected simulation correctness and build systems.

### Compute SNAP Energy and Virial Tally Issue

A significant bug was identified and fixed regarding the `compute_snap` command. As detailed in [issue #4829](https://github.com/lammps/lammps/issues/4829), the compute was attempting to access global potential energy and virial without forcing their tally on the required timestep. This caused errors when `thermo` output was not set to run on the same step as the compute.

The fix involved adding `peflag`, `timeflag`, and `pressflag` settings to the compute's constructor, ensuring energy and virial tallies occur automatically when needed. This aligns with LAMMPS's design principle that computes requiring energy/virial information should trigger those tallies, as documented in the code comments in `integrate.cpp`.

### GPU Package Bug Fixes

Multiple GPU-related issues were resolved:

- [Issue #4712](https://github.com/lammps/lammps/issues/4712): The GPU-accelerated `born/coul/long/cs/gpu` pair style was producing incorrect forces for core-shell models, leading to simulation crashes. This was specific to the GPU variant and did not affect the reference CPU implementation.

- [Issue #4798](https://github.com/lammps/lammps/issues/4798): A CUDA illegal memory access occurred when using `package kokkos comm host`. The issue stemmed from improper handling when communication was forced to host while computations remained on device. This highlights the complexity of managing host-device synchronization in GPU-accelerated molecular dynamics codes.

### INTEL Package Monte Carlo Bug

[Issue #4801](https://github.com/lammps/lammps/issues/4801) revealed a critical bug in the INTEL-accelerated implementation of `fix atom/swap`. The fix was accepting all swap attempts regardless of energy change (Delta E), effectively breaking Monte Carlo acceptance criteria. This only occurred with INTEL acceleration enabled, while reference CPU implementations correctly applied the Metropolis acceptance probability.

The issue demonstrates the risk of acceleration paths diverging from reference implementations. Users running canonical ensemble Monte Carlo swaps with INTEL acceleration should verify they're using a version where this has been addressed.

### Hybrid Scaled Kokkos Synchronization

[Issue #4788](https://github.com/lammps/lammps/issues/4788) identified a fundamental synchronization problem in `pair_hybrid_scaled_kk`. When combining custom Kokkos-enabled pair styles that compute on GPU, the host-side code attempted to scale and sum forces without synchronizing device-to-host data transfer. This resulted in all forces being zero.

The root cause was that the Kokkos implementation was nearly identical to the non-Kokkos version, performing scaling on host data while computation remained on device. This raises broader questions about whether `hybrid/scaled/kk` should be redesigned to operate entirely on device for better performance and correctness.

## Ongoing Issues and Community Feedback

Several issues remain open, reflecting active community engagement and areas needing attention.

### SCAFACOS Build Issues

[Issue #4815](https://github.com/lammps/lammps/issues/4815) reports a linker error when building LAMMPS with the SCAFACOS module. The error involves undefined references to gfortran symbols like `_gfortran_st_rewind`, `_gfortran_transfer_character_write`, and others. This occurs because SCAFACOS links Fortran libraries that aren't properly propagated in the CMake configuration.

A workaround was documented involving manual linking of `libgfortran.so.5`, but this highlights a gap in the build system's handling of mixed-language dependencies. Users following modern build practices expect CMake to handle such dependencies automatically.

### MLIAP Interface Limitations

[Issue #4814](https://github.com/lammps/lammps/issues/4814) questions whether the `forward_exchange` function in the MLIAP (Machine Learning Interatomic Potential) unified interface supports CPU execution. The user observed that systems with different atom counts behaved differently on CPU versus GPU, with GPU working correctly but CPU failing after one step for larger systems.

Similarly, [issue #4787](https://github.com/lammps/lammps/issues/4787) requests box information passing for MACELES-LAMMPS integration via MLIAP. The current interface lacks box transformation capability needed for reciprocal space operations in the LES (Local Environment Scaling) method.

### Feature Requests in Pipeline

Several feature requests indicate future development directions:

- [Issue #4803](https://github.com/lammps/lammps/issues/4803): Request to read dump files in triclinic/general format. Currently, LAMMPS can write this format and read data files in it, but dump file reading is not supported. This creates workflow friction when restarting from configurations saved in this widely-used formalism.

- [Issue #4561](https://github.com/lammps/lammps/issues/4561): Request for library API access to neighbor lists from Kokkos styles. Currently, GPU-accelerated pair styles keep neighbor lists on device with no way to access them from Python for analysis, even via device pointers.

- [Issue #4763](https://github.com/lammps/lammps/issues/4763): Suggestion to align with RDKit's Molecule JSON format for better interoperability with chemical informatics workflows.

### Longstanding Physics Bugs

Some issues have been open for extended periods, indicating complex underlying problems:

- [Issue #4611](https://github.com/lammps/lammps/issues/4611): Center of mass velocity jumps when combining `fix srd` and `fix deform`, especially when disabling the thermostat. This has implications for accurate shear flow simulations with SRD fluids.

- [Issue #4602](https://github.com/lammps/lammps/issues/4602): Velocity profile kinks near periodic boundaries when using `fix srd` with `fix deform`. The issue relates to how SRD handles particle bins crossing periodic boundaries during grid shifts.

- [Issue #4770](https://github.com/lammps/lammps/issues/4770): Incorrect kernel gradients in `ComputeRHEOVShift::correct_type_interface()`, where SPH kernel gradients were not being properly calculated because `calc_dw` was never called.

- [Issue #4717](https://github.com/lammps/lammps/issues/4717): Inconsistencies in dipolar energy between `spin/dipole/long` and `spin/dipole/cut` pair styles. The long-range version produces incorrect energies for certain spin configurations, while the cutoff version matches analytical expectations.

## Looking Ahead

The December 2025 activity reveals LAMMPS's ongoing evolution in several key areas:

1. **Visualization enhancements** making it easier to interpret complex simulation results
2. **GPU acceleration maturity** as synchronization bugs are identified and addressed
3. **Build system improvements** needed for better handling of mixed-language dependencies
4. **Machine learning integration** expanding through MLIAP and related interfaces
5. **Physics correctness** through fixes of long-standing numerical issues

The transparency support in `dump image` represents the kind of user-driven improvement that directly addresses workflow pain points. Meanwhile, the various GPU-related bug fixes highlight the challenges of maintaining correctness across multiple acceleration backends (Kokkos, INTEL, native GPU).

For developers following LAMMPS development, the repository remains highly active with contributions from both core developers and community members. Issues are being opened and resolved at a steady pace, indicating healthy project maintenance and responsiveness to user feedback.