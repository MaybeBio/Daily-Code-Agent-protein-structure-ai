# torchsim/torch-sim Overview
[`torch-sim`](https://github.com/torchsim/torch-sim/README.md#L3) provides an atomistic simulation engine for high-performance molecular dynamics, structural optimization, and static calculations. It leverages PyTorch for efficient computation, particularly for machine learning interatomic potentials.

The [`SimState`](https://github.com/torchsim/torch-sim/torch_sim/state.py#L121) data structure serves as the engine's central container for atomistic system properties. It represents systems as PyTorch tensors, enabling batched operations and direct GPU computation. [Core Simulation State Management](#atomistic-simulation-engine-core-core-simulation-state-management) provides further details on [`SimState`](https://github.com/torchsim/torch-sim/torch_sim/state.py#L121).

High-level runner functions orchestrate simulation execution. These functions include [`integrate`](https://github.com/torchsim/torch-sim/torch_sim/runners.py#L317) for molecular dynamics, [`optimize`](https://github.com/torchsim/torch-sim/torch_sim/runners.py#L638) for geometry relaxations, and [`static`](https://github.com/torchsim/torch-sim/torch_sim/runners.py#L844) for single-point calculations. These runners abstract away complexities and manage trajectory reporting. [High-Level Simulation Runners](#atomistic-simulation-engine-core-high-level-simulation-runners) discusses these functions further.

The engine includes a suite of PyTorch-accelerated molecular dynamics integrators. They support the time evolution of atomistic systems under NVE, NVT, and NPT ensembles for batched simulations with periodic boundary conditions. [Simulation Integrators](#simulation-integrators) covers these implementations.

Geometry optimization algorithms relax atomic structures to minimize system energy. This includes Gradient Descent, FIRE, BFGS, and L-BFGS, supporting batched operations and cell optimization through a filter-based design. [Geometry Optimization Algorithms](#geometry-optimization-algorithms) provides a detailed discussion of these optimizers.

An autobatching system dynamically manages GPU memory and optimizes batch processing for diverse simulation scenarios. It efficiently groups multiple atomistic systems and dynamically handles their convergence. [Autobatching Mechanisms](#atomistic-simulation-engine-core-autobatching-mechanisms) offers more information.

Multiple neighbor list implementations efficiently identify interatomic interactions within a specified cutoff. An automatic fallback mechanism ensures optimal performance by prioritizing available hardware-accelerated solutions and providing pure PyTorch alternatives. [Neighbor List Algorithms](#neighbor-list-algorithms) provides further details.

The framework includes a variety of models for calculating interatomic energies, forces, and stresses. These range from classical potentials, such as Lennard-Jones, to wrappers for external machine learning potentials. All models adhere to a common interface for consistent integration. [Model Implementations and Integration](#model-implementations-and-integration) describes these models.

Tools for calculating correlation properties enable analysis of simulation dynamics and transport phenomena. This includes general time correlation functions, velocity autocorrelation, and heat flux autocorrelation, computed using FFT-based methods with PyTorch acceleration. [Advanced Physical Property Calculations](#atomistic-simulation-engine-core-advanced-physical-property-calculations) and [Simulation Property Calculators](#simulation-property-calculators) cover these capabilities.

Auxiliary functionalities support the core engine, including applying constraints, converting to and from external atomistic file formats (e.g., ASE, Pymatgen), and providing specialized mathematical utilities. [Auxiliary Simulation Functionalities](#atomistic-simulation-engine-core-auxiliary-simulation-functionalities) elaborates on these.

Reproducibility mechanisms ensure deterministic simulation trajectories. This involves explicit seeding of the [`torch.Generator`](https://github.com/torchsim/torch-sim/torch_sim/state.py#L40) within [`SimState.rng`](https://github.com/torchsim/torch-sim/docs/user/reproducibility.md#L44) and consistent batch composition for stochastic integrators and batched simulations. [Ensuring Reproducibility in TorchSim](#user-guide-to-core-concepts-ensuring-reproducibility-in-torchsim) provides detailed guidance.

The User Guide section [User Guide to Core Concepts](#user-guide-to-core-concepts) offers a high-level overview of these fundamental concepts for new users.

