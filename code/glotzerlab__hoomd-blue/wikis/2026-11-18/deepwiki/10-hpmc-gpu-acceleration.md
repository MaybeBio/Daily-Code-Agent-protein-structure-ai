# HPMC GPU Acceleration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [hoomd/RNGIdentifiers.h](hoomd/RNGIdentifiers.h)
- [hoomd/hpmc/ComputeFreeVolume.h](hoomd/hpmc/ComputeFreeVolume.h)
- [hoomd/hpmc/ComputeFreeVolumeGPU.cuh](hoomd/hpmc/ComputeFreeVolumeGPU.cuh)
- [hoomd/hpmc/ComputeFreeVolumeGPU.h](hoomd/hpmc/ComputeFreeVolumeGPU.h)
- [hoomd/hpmc/HPMCCounters.h](hoomd/hpmc/HPMCCounters.h)
- [hoomd/hpmc/IntegratorHPMCMonoGPU.cu](hoomd/hpmc/IntegratorHPMCMonoGPU.cu)
- [hoomd/hpmc/IntegratorHPMCMonoGPU.cuh](hoomd/hpmc/IntegratorHPMCMonoGPU.cuh)
- [hoomd/hpmc/IntegratorHPMCMonoGPU.h](hoomd/hpmc/IntegratorHPMCMonoGPU.h)
- [hoomd/hpmc/IntegratorHPMCMonoGPUMoves.cuh](hoomd/hpmc/IntegratorHPMCMonoGPUMoves.cuh)
- [hoomd/hpmc/IntegratorHPMCMonoGPUTypes.cuh](hoomd/hpmc/IntegratorHPMCMonoGPUTypes.cuh)
- [hoomd/hpmc/UpdaterGCAGPU.cu](hoomd/hpmc/UpdaterGCAGPU.cu)
- [hoomd/hpmc/UpdaterGCAGPU.cuh](hoomd/hpmc/UpdaterGCAGPU.cuh)
- [hoomd/hpmc/UpdaterGCAGPU.h](hoomd/hpmc/UpdaterGCAGPU.h)

</details>



This page documents the GPU acceleration implementation for the Hard Particle Monte Carlo (HPMC) simulation engine in HOOMD-blue. It explains how HPMC simulations leverage GPU hardware for significant performance gains, including architectural choices, kernel optimization strategies, and execution patterns specific to the GPU implementation. For information about the HPMC simulation engine in general, see [Hard Particle Monte Carlo (HPMC)](#3), and for CPU-specific implementations, see [HPMC Integrators](#3.1).

## Overview of HPMC GPU Implementation

The HPMC GPU implementation uses NVIDIA CUDA or AMD HIP through a unified interface to execute Monte Carlo moves and overlap checks in parallel on the GPU. The implementation enables efficient simulation of hard particle systems with various shape types on GPU hardware.

### Core Architecture

```mermaid
classDiagram
    class IntegratorHPMCMono {
        +update(timestep)
        #d_postype
        #d_orientation
        #m_overlap_idx
    }
    
    class IntegratorHPMCMonoGPU {
        +update(timestep)
        -m_cl: CellList
        -m_excell_idx: GPUArray
        -m_excell_size: GPUArray
        -m_trial_postype: GPUArray
        -m_trial_orientation: GPUArray
        -m_reject: GPUArray
        -initializeExcellMem()
        -updateCellWidth()
    }
    
    class CellList {
        +compute(timestep)
        +getNmax()
        +getDim()
    }
    
    class Autotuner {
        +begin()
        +end()
        +getParam()
    }
    
    IntegratorHPMCMono <|-- IntegratorHPMCMonoGPU
    IntegratorHPMCMonoGPU --> CellList: uses
    IntegratorHPMCMonoGPU --> Autotuner: has many
```

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:137-210](), [hoomd/hpmc/IntegratorHPMCMonoGPU.h:213-316]()

### GPU Kernels and Execution Model

The HPMC GPU implementation uses several specialized kernels to execute the Monte Carlo algorithm:

```mermaid
flowchart TB
    subgraph "HPMC GPU Execution Flow"
        init["Initialize System"] --> moves["Generate Trial Moves\nhpmc_gen_moves"]
        moves --> narrow["Narrow Phase Overlap Check\nhpmc_narrow_phase"]
        narrow --> cvg{"Converged?"}
        cvg -- No --> narrow
        cvg -- Yes --> update["Update Particle Data\nhpmc_update_pdata"]
        update --> shift["Shift Particles\nhpmc_shift"]
    end
```

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:317-407](), [hoomd/hpmc/IntegratorHPMCMonoGPU.cuh:44-366](), [hoomd/hpmc/IntegratorHPMCMonoGPUMoves.cuh:30-167]()

## Key Components

### Cell List and Expanded Cell List

The GPU implementation relies heavily on cell lists for efficient overlap detection. Unlike CPU implementations that can use callbacks for neighbor queries, the GPU uses an expanded cell list approach that caches all potential neighbors in memory for efficient parallel access.

```mermaid
flowchart LR
    subgraph "Cell List Structure"
        cells["Regular Cell List\nStores particle indices"] --> excell["Expanded Cell List\nPrecomputed neighbor particles\nm_excell_idx, m_excell_size"]
        excell --> overlap["Overlap Checking\nParallel kernel execution"]
    end
```

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:158-164](), [hoomd/hpmc/IntegratorHPMCMonoGPU.h:206-210](), [hoomd/hpmc/IntegratorHPMCMonoGPU.cu:14-65]()

### Trial Move Generation

The trial move generation phase creates potential new positions and orientations for particles:

```mermaid
flowchart TB
    subgraph "Trial Move Generation"
        init["Initialize RNG per particle"] --> select["Select move type\n(Translation or Rotation)"]
        select --> trans["Translation Move\nmove_translate()"]
        select --> rot["Rotation Move\nmove_rotate()"]
        trans --> store["Store trial position\nin m_trial_postype"]
        rot --> store
        store --> reject["Initial rejection check\nStore in m_reject_out_of_cell"]
    end
```

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPUMoves.cuh:30-167](), [hoomd/hpmc/Moves.h]()

### Narrow Phase Overlap Detection

The overlap detection is the most computationally intensive part of the algorithm. It's implemented as a custom kernel that efficiently utilizes shared memory and threads:

```mermaid
flowchart TB
    subgraph "Narrow Phase Overlap Detection"
        load["Load particle data\nand parameters"] --> queue["Fill neighbor queue\nfrom excell list"]
        queue --> check["Check overlaps in parallel\nWithin thread blocks"]
        check --> flag["Flag rejections\nAtomic updates to m_reject"]
        flag --> next["Process next batch\nor complete"]
    end
```

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.cuh:44-366]()

### Auto-tuning for GPU Performance

The implementation uses several autotuners to optimize kernel launch parameters for different hardware:

```mermaid
flowchart LR
    subgraph "GPU Autotuners"
        direction LR
        moves["m_tuner_moves\nOptimizes Trial Move Generation"] 
        narrow["m_tuner_narrow\nOptimizes Overlap Detection\n(block size, threads per particle, overlap threads)"]
        update["m_tuner_update_pdata\nOptimizes Particle Data Updates"]
        excell["m_tuner_excell_block_size\nOptimizes Expanded Cell Generation"]
        conv["m_tuner_convergence\nOptimizes Convergence Check"]
    end
```

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:166-179](), [hoomd/hpmc/IntegratorHPMCMonoGPU.h:226-279]()

## Memory Management and Data Flow

The GPU implementation manages several arrays to track the simulation state:

| GPU Array | Purpose |
|-----------|---------|
| `m_trial_postype` | Candidate new positions and types |
| `m_trial_orientation` | Candidate new orientations |
| `m_trial_vel` | Additional auxiliary variables |
| `m_reject_out_of_cell` | Flags particles that leave their cell |
| `m_reject` | Flags particles that have overlaps |
| `m_excell_idx` | Expanded cell list particles |
| `m_excell_size` | Number of particles in each expanded cell |
| `m_condition` | Convergence condition flag |

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:181-196]()

### Data Flow in Update Method

```mermaid
sequenceDiagram
    participant Host as "Host CPU"
    participant GPU as "GPU Device"
    participant Cell as "Cell List"
    participant Mem as "GPU Memory"
    
    Host->>Cell: compute(timestep)
    Host->>Mem: Initialize m_reject, trial arrays
    Host->>GPU: hpmc_excell
    GPU->>Mem: Populate excell_idx, excell_size
    
    loop For each nselect iteration
        Host->>GPU: hpmc_gen_moves
        GPU->>Mem: Generate trial positions & orientations
        
        loop Until converged
            Host->>GPU: hpmc_narrow_phase
            GPU->>Mem: Check overlaps, update rejection flags
            Host->>GPU: hpmc_check_convergence
            GPU->>Host: Convergence status
        end
        
        Host->>GPU: hpmc_update_pdata
        GPU->>Mem: Update accepted positions & orientations
    end
    
    Host->>GPU: hpmc_shift
    GPU->>Mem: Apply random shift to all particles
```

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:317-811]()

## Parallel Overlap Detection Strategy

The HPMC GPU implementation uses a sophisticated parallel overlap detection strategy that balances work across thread blocks:

```mermaid
flowchart TB
    subgraph "Parallel Overlap Detection Model"
        direction TB
        block["Thread Block"] --> groups["Thread Groups\nOne group per particle"]
        groups --> threads["Threads within group\nProcess neighbor particles in parallel"]
        threads --> queue["Queue potential overlaps\nShared memory queue"]
        queue --> checks["Parallel overlap tests\nShape-specific algorithms"]
    end
```

The overlap detection uses tunable parameters:
- **Block size**: Total number of threads in a block
- **Threads per particle (tpp)**: Number of threads working on each particle's neighbors
- **Overlap threads**: For shapes supporting parallel overlap computations

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.cuh:44-366](), [hoomd/hpmc/IntegratorHPMCMonoGPU.h:245-267]()

## Random Number Generation

The implementation uses a consistent random number generation approach:

```mermaid
flowchart LR
    subgraph "HPMC Random Number Generation"
        seed["Random Seeds\nSpecific to operation type"] --> gen["RandomGenerator\nHookedConcurrentRNG"]
        gen --> moves["Trial Move Generation"]
        gen --> shuffle["Particle Selection Order"]
        gen --> shift["System-wide Shifts"]
    end
```

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:322-324](), [hoomd/RNGIdentifiers.h:26-30](), [hoomd/hpmc/IntegratorHPMCMonoGPUMoves.cuh:123-125]()

## Convergence Handling for Move Acceptance

A unique aspect of the GPU implementation is handling convergence of acceptance/rejection decisions:

```mermaid
flowchart TB
    subgraph "Convergence Handling"
        init["Initialize: d_reject = d_reject_out_of_cell"] --> overlap["Run narrow phase kernel\nCheck for overlaps"]
        overlap --> update["Update rejection flags\nd_reject_out = result"]
        update --> check["Check convergence\nAny rejections changed?"]
        check -->|"Yes"| swap["Swap buffers\nd_reject ↔ d_reject_out"]
        swap --> overlap
        check -->|"No"| done["Converged: Apply accepted moves"]
    end
```

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:543-713](), [hoomd/hpmc/IntegratorHPMCMonoGPU.cu:107-140]()

## Related GPU-Accelerated Functionality

### Free Volume Computation

The HPMC GPU implementation also provides GPU-accelerated methods for computing free volume:

```mermaid
flowchart LR
    ComputeFreeVolume["ComputeFreeVolume\nBase class"] --> ComputeFreeVolumeGPU["ComputeFreeVolumeGPU\nGPU-accelerated implementation"]
    ComputeFreeVolumeGPU --> gpu_hpmc_free_volume["gpu_hpmc_free_volume\nParallel volume sampling kernel"]
```

Sources: [hoomd/hpmc/ComputeFreeVolumeGPU.h:37-301](), [hoomd/hpmc/ComputeFreeVolumeGPU.cuh:156-354]()

### Cluster Moves

Cluster moves are also GPU-accelerated through the `UpdaterGCAGPU` class:

```mermaid
flowchart TB
    UpdaterGCA["UpdaterGCA\nBase Geometric Cluster Algorithm"] --> UpdaterGCAGPU["UpdaterGCAGPU\nGPU-accelerated implementation"]
    UpdaterGCAGPU --> kernels["GPU Kernels\n- Overlap detection\n- Connected components\n- Cluster transformation"]
```

Sources: [hoomd/hpmc/UpdaterGCAGPU.h:21-225](), [hoomd/hpmc/UpdaterGCAGPU.cuh:38-725]()

## Performance Considerations

Several factors affect performance of the GPU-accelerated HPMC implementation:

1. **Shape Complexity**: More complex shapes require more computational resources for overlap checks
2. **System Size**: Larger systems can better utilize GPU parallelism but may require more memory
3. **Cell List Dimensions**: The cell list dimensions affect memory usage and neighbor-finding efficiency
4. **Auto-tuning**: Performance depends heavily on finding optimal kernel launch parameters

The implementation uses auto-tuning to optimize:
- Block sizes for various kernels
- Threads per particle for overlap checks
- Parallel threads for shape-specific overlap algorithms

Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:166-179](), [hoomd/hpmc/IntegratorHPMCMonoGPU.h:266-279]()

## Implementation Limitations

The GPU implementation has some limitations compared to the CPU version:

1. **Box Size Requirements**: The simulation box must be large enough to apply the minimum image convention
   ```
   if ((global_box.getPeriodic().x && nearest_plane_distance.x <= this->m_nominal_width * 2)
       || (global_box.getPeriodic().y && nearest_plane_distance.y <= this->m_nominal_width * 2)
       || (this->m_sysdef->getNDimensions() == 3 && global_box.getPeriodic().z
           && nearest_plane_distance.z <= this->m_nominal_width * 2))
   ```
   Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.h:337-356]()

2. **Memory Constraints**: GPU memory limits the maximum system size and shape complexity
   ```
   if (min_shared_bytes >= args.devprop.sharedMemPerBlock)
       throw std::runtime_error("Insufficient shared memory for HPMC kernel: reduce number of particle types or size of shape parameters");
   ```
   Sources: [hoomd/hpmc/IntegratorHPMCMonoGPU.cuh:415-417]()

3. **Shape Support**: Not all shapes may have the same level of optimization on GPU

---