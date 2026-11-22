

HOOMD-blue leverages MPI (Message Passing Interface) to enable large-scale molecular dynamics simulations across multiple processors and nodes. This parallel computing approach allows you to distribute computational workload and memory requirements, making it possible to simulate systems with millions of particles that would be impossible to handle on a single machine.

## Understanding MPI Communication in HOOMD-blue

At its core, HOOMD-blue's MPI implementation follows a domain decomposition strategy where the global simulation box is divided into smaller sub-domains, each assigned to a different MPI process. This approach minimizes communication overhead while maximizing computational efficiency.

The foundation of HOOMD-blue's MPI infrastructure is built upon several key components:

### MPI Wrapper Functions

HOOMD-blue provides convenient wrapper functions in `HOOMDMPI.h` that simplify common MPI operations using serialization. These wrappers handle the complexity of data serialization and deserialization automatically:

```cpp
// Broadcast a value from root to all processes
template<typename T> void bcast(T& val, unsigned int root, const MPI_Comm mpi_comm)

// Scatter vector elements to different processes
template<typename T> void scatter_v(const std::vector<T>& in_values, T& out_value, unsigned int root, const MPI_Comm mpi_comm)

// Gather values from all processes onto root
template<typename T> void gather_v(const T& in_value, std::vector<T>& out_values, unsigned int root, const MPI_Comm mpi_comm)
```

These functions use the Cereal serialization library to handle complex data types automatically, making it easy to send particle data, forces, and other simulation state between processes.

Sources: [HOOMDMPI.h#L127-L173](hoomd/HOOMDMPI.h#L127-L173), [HOOMDMPI.h#L253-L330](hoomd/HOOMDMPI.h#L253-L330)

### Domain Decomposition

The `DomainDecomposition` class is responsible for dividing the global simulation box into sub-domains assigned to each MPI process. It optimizes the decomposition to minimize surface area between domains, which reduces communication overhead.

```cpp
// Create a domain decomposition
DomainDecomposition decomposition(exec_conf, global_box_L, nx, ny, nz);

// Calculate the local box for this process
BoxDim local_box = decomposition.calculateLocalBox(global_box);

// Determine which process owns a particle
unsigned int owner_rank = decomposition.placeParticle(global_box, particle_position, cart_ranks);
```

The decomposition can be uniform (equal-sized domains) or non-uniform (useful for systems with inhomogeneous particle distributions like vapor-liquid interfaces).

Sources: [DomainDecomposition.h#L49-48](hoomd/DomainDecomposition.h#L49-48), [DomainDecomposition.h#L159-L163](hoomd/DomainDecomposition.h#L159-L163)

## The Three-Stage Communication Pattern

HOOMD-blue implements a sophisticated three-stage communication pattern that efficiently handles particle migration and ghost particle exchange:

### Stage 1: Particle Migration

In this stage, particles that have moved outside their local domain boundaries are transferred to the appropriate neighboring processes. This happens infrequently, typically only when the neighbor list needs rebuilding.

```cpp
// Force particle migration (e.g., after neighbor list rebuild)
communicator.forceMigrate();

// The actual migration is handled automatically in communicate()
communicator.communicate(timestep);
```

When particles migrate, ownership is transferred completely - the sending process deletes the particle, and the receiving process adds it to its local particle data.

Sources: [Communicator.h#L299-L307](hoomd/Communicator.h#L299-L307), [Communicator.h#L337-L347](hoomd/Communicator.h#L337-L347)

### Stage 2: Ghost Exchange

Ghost particles are copies of particles from neighboring domains that are within the cutoff distance + buffer distance from the local domain boundary. These are needed to correctly calculate forces on particles near domain boundaries.

```cpp
// Exchange ghost particles with neighbors
communicator.exchangeGhosts();
```

The ghost layer width is determined by the maximum cutoff radius plus a buffer distance, ensuring that all necessary particle information is available for force calculations.

Sources: [Communicator.h#L349-L357](hoomd/Communicator.h#L349-L357)

### Stage 3: Ghost Position Updates

Between particle migrations, only the positions of existing ghost particles need to be updated, which is more efficient than rebuilding the entire ghost particle list.

```cpp
// Begin updating ghost positions (non-blocking)
communicator.beginUpdateGhosts(timestep);

// ... perform other computations ...

// Complete the ghost update
communicator.finishUpdateGhosts(timestep);
```

This uses non-blocking MPI communication to allow overlap with other computations, improving overall performance.

Sources: [Communicator.h#L307-L330](hoomd/Communicator.h#L307-L330)

## Communication Flags and Data Management

HOOMD-blue uses a sophisticated flag system to determine which particle properties need to be communicated:

```cpp
// Define communication flags
CommFlags flags;
flags[comm_flag::position] = 1;    // Communicate positions
flags[comm_flag::velocity] = 1;    // Communicate velocities
flags[comm_flag::net_force] = 1;   // Communicate forces

// Set the flags for the communicator
communicator.setFlags(flags);
```

Available communication flags include:
- `tag`: Particle identifiers
- `position`: Particle positions
- `velocity`: Particle velocities
- `charge`: Particle charges
- `diameter`: Particle diameters
- `orientation`: Particle orientations
- `net_force`: Forces on particles
- `net_torque`: Torques on particles

This selective communication minimizes data transfer by only sending the information actually needed for the current computation.

Sources: [Communicator.h#L57-80](hoomd/Communicator.h#L57-80), [Communicator.h#L278-284](hoomd/Communicator.h#L278-L284)

## Running HOOMD-blue with MPI

To run a HOOMD-blue simulation in parallel, you need to use MPI's launch mechanism:

```bash
# Run on 4 processes
mpirun -np 4 python -m hoomd my_simulation.py

# Run on 16 processes across 4 nodes (4 processes per node)
mpirun -np 16 --map-by ppr:4:node python -m hoomd my_simulation.py
```

> [!TIP]
> For optimal performance, ensure that the number of MPI processes matches your domain decomposition. Use powers of 2 (2, 4, 8, 16, 32) for best load balancing, especially for cubic simulation boxes.

## Performance Considerations

When using MPI with HOOMD-blue, several factors affect performance:

### Domain Decomposition Strategy

The shape of your domain decomposition significantly impacts performance. For cubic boxes, aim for roughly equal dimensions (e.g., 4×2×2 is better than 8×1×1).

### Ghost Layer Width

The ghost layer width affects both communication volume and frequency of particle migration:

```cpp
// Get the current ghost layer width
Scalar max_width = communicator.getGhostLayerMaxWidth();
```

Larger ghost layers reduce migration frequency but increase communication volume.

### Load Balancing

For systems with non-uniform particle densities, consider using non-uniform domain decomposition:

```cpp
// Create non-uniform decomposition
std::vector<Scalar> fxs = {0.0, 0.3, 0.7, 1.0};  // 30% and 40% splits
std::vector<Scalar> fys = {0.0, 0.5, 1.0};        // 50% split
std::vector<Scalar> fzs = {0.0, 1.0};             // Uniform in z

DomainDecomposition decomposition(exec_conf, box_L, fxs, fys, fzs);
```

Sources: [DomainDecomposition.h#L68-73](hoomd/DomainDecomposition.h#L68-73)

## Advanced Features

### Two-Level Decomposition

HOOMD-blue supports two-level decomposition for hybrid MPI+GPU systems, where processes on the same node share GPU resources:

```cpp
// Enable two-level decomposition
DomainDecomposition decomposition(exec_conf, box_L, 0, 0, 0, true);
```

This optimizes communication patterns for multi-GPU nodes.

### Callback System

The Communicator class provides a callback system for custom communication needs:

```cpp
// Request a specific ghost layer width
communicator.getGhostLayerWidthRequestSignal().connect([](unsigned int type) {
    return 2.5;  // Custom ghost width for this type
});

// Request specific communication flags
communicator.getCommFlagsRequestSignal().connect([](uint64_t timestep) {
    CommFlags flags;
    flags[comm_flag::position] = 1;
    flags[comm_flag::velocity] = 1;
    return flags;
});
```

This allows modules to dynamically adjust communication parameters based on their requirements.

Sources: [Communicator.h#L172-201](hoomd/Communicator.h#L172-201)

## Best Practices

1. **Profile your simulation**: Use HOOMD-blue's built-in profiling tools to identify communication bottlenecks.

2. **Optimize domain decomposition**: Experiment with different domain shapes to find the optimal configuration for your system.

3. **Minimize ghost layer width**: Use the smallest ghost layer that maintains simulation accuracy.

4. **Balance workload**: Ensure each process has roughly the same number of particles to avoid idle time.

5. **Use appropriate MPI process placement**: Consider network topology when placing processes on multi-node systems.

HOOMD-blue's MPI implementation provides a robust foundation for large-scale molecular dynamics simulations, enabling researchers to tackle problems of unprecedented scale while maintaining high computational efficiency.