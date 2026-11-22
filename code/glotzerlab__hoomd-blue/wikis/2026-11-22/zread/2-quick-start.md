

Welcome to HOOMD-blue! This guide will help you get up and running with your first particle simulation in just a few minutes. HOOMD-blue is a powerful Python package that performs particle simulations on both CPUs and GPUs, supporting both molecular dynamics and hard particle Monte Carlo methods.

## What You'll Accomplish

In this Quick Start, you'll:
1. Install HOOMD-blue on your system
2. Create a basic molecular dynamics simulation
3. Run the simulation and see the results

This guide focuses on getting you started quickly with a working example. For more detailed explanations of the concepts, refer to the other guides in our documentation.

## Installation

HOOMD-blue is available through conda-forge, making installation straightforward. The simplest way to install is:

```bash
micromamba install hoomd
```

HOOMD-blue will automatically detect if your system has a GPU and install the appropriate version. If you want to force a specific installation type:

```bash
# For GPU support
export CONDA_OVERRIDE_CUDA="12.6"
micromamba install "hoomd=*gpu*" "cuda-version=12.6"

# For CPU-only
micromamba install "hoomd=*cpu*"
```

> [!TIP]
> If you encounter CUDA version errors, replace "12.6" with the CUDA version noted in the error message. HOOMD-blue also supports CUDA 11.8.

Sources: [INSTALLING.rst#L19-46](INSTALLING.rst#L19-46)

## Your First Simulation

Let's create a simple molecular dynamics simulation of Lennard-Jones particles. This is a classic model in computational physics and serves as a great starting point.

### Step 1: Import HOOMD-blue

Start by importing the necessary modules:

```python
import hoomd
```

### Step 2: Set Up the Simulation Device

HOOMD-blue can run on both CPUs and GPUs. Create a device object to specify where your simulation will run:

```python
# For CPU simulation
device = hoomd.device.CPU()

# Or for GPU simulation (if available)
device = hoomd.device.GPU()
```

### Step 3: Create the Simulation Object

The `Simulation` class is the central object that manages your simulation:

```python
sim = hoomd.Simulation(device=device, seed=42)
```

The `seed` parameter ensures reproducible results by initializing the random number generator.

Sources: [simulation.py#L34-57](hoomd/simulation.py#L34-57)

### Step 4: Define the Force Field

For molecular dynamics, we need to define the forces between particles. Let's set up a Lennard-Jones potential:

```python
# Create a neighbor list with a buffer
cell = hoomd.md.nlist.Cell(buffer=0.4)

# Create the Lennard-Jones pair potential
lj = hoomd.md.pair.LJ(nlist=cell)
lj.params[('A', 'A')] = dict(epsilon=1.0, sigma=1.0)
lj.r_cut[('A', 'A')] = 2.5
```

This code sets up a Lennard-Jones potential with standard parameters where particles of type 'A' interact with each other.

### Step 5: Set Up the Integrator

The integrator defines how particles move over time. We'll use the NVT ensemble (constant number of particles, volume, and temperature):

```python
# Create the integrator with a time step
integrator = hoomd.md.Integrator(dt=0.005)
integrator.forces.append(lj)

# Add a thermostat to maintain temperature
bussi = hoomd.md.methods.thermostats.Bussi(kT=1.5)
nvt = hoomd.md.methods.ConstantVolume(filter=hoomd.filter.All(), thermostat=bussi)
integrator.methods.append(nvt)

# Attach the integrator to the simulation
sim.operations.integrator = integrator
```

### Step 6: Initialize the System State

Now we need to create an initial configuration of particles. For this example, we'll create a simple cubic lattice:

```python
# Create a snapshot with particles on a cubic lattice
snapshot = hoomd.Snapshot()
snapshot.particles.N = 1000
snapshot.particles.position[:] = [[i, j, k] 
                                  for i in range(10) 
                                  for j in range(10) 
                                  for k in range(10)]
snapshot.particles.types = ['A']
snapshot.particles.typeid[:] = [0] * 1000

# Set the simulation box
snapshot.configuration.box = [10, 10, 10, 0, 0, 0]

# Initialize the simulation state
sim.create_state_from_snapshot(snapshot)
```

Sources: [simulation.py#L248-292](hoomd/simulation.py#L248-292)

### Step 7: Run the Simulation

Finally, let's run the simulation for a few thousand steps:

```python
# Run the simulation
sim.run(1_000)
```

This will advance the simulation by 1,000 time steps, updating particle positions and velocities according to the forces and integrator we defined.

Sources: [simulation.py#L484-546](hoomd/simulation.py#L484-546)

## Complete Example

Here's the complete script for your first simulation:

```python
import hoomd

# Create the simulation device and simulation object
device = hoomd.device.CPU()
sim = hoomd.Simulation(device=device, seed=42)

# Set up the force field
cell = hoomd.md.nlist.Cell(buffer=0.4)
lj = hoomd.md.pair.LJ(nlist=cell)
lj.params[('A', 'A')] = dict(epsilon=1.0, sigma=1.0)
lj.r_cut[('A', 'A')] = 2.5

# Set up the integrator
integrator = hoomd.md.Integrator(dt=0.005)
integrator.forces.append(lj)
bussi = hoomd.md.methods.thermostats.Bussi(kT=1.5)
nvt = hoomd.md.methods.ConstantVolume(filter=hoomd.filter.All(), thermostat=bussi)
integrator.methods.append(nvt)
sim.operations.integrator = integrator

# Initialize the system
snapshot = hoomd.Snapshot()
snapshot.particles.N = 1000
snapshot.particles.position[:] = [[i, j, k] 
                                  for i in range(10) 
                                  for j in range(10) 
                                  for k in range(10)]
snapshot.particles.types = ['A']
snapshot.particles.typeid[:] = [0] * 1000
snapshot.configuration.box = [10, 10, 10, 0, 0, 0]
sim.create_state_from_snapshot(snapshot)

# Run the simulation
sim.run(1_000)

print("Simulation completed successfully!")
```

## Next Steps

Congratulations! You've just run your first HOOMD-blue simulation. From here, you can:

1. **Save your results**: Add a GSD writer to save trajectory data
2. **Analyze your data**: Use tools like freud to analyze particle configurations
3. **Explore different methods**: Try hard particle Monte Carlo (HPMC) simulations
4. **Scale up**: Run larger simulations on GPUs for better performance

For more detailed information on any of these topics, check out our other documentation guides.
