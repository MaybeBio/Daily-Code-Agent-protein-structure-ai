# Albert Cañellas Solé

**Computational protein design** · PhD researcher at the [Barcelona Supercomputing Center](https://www.bsc.es/), EAPM group

[![ORCID](https://img.shields.io/badge/ORCID-0000--0001--8120--888X-A6CE39?style=flat&logo=orcid&logoColor=white)](https://orcid.org/0000-0001-8120-888X)
[![BSC](https://img.shields.io/badge/BSC-EAPM-003B71?style=flat)](https://www.bsc.es/)

> **What I'm working on.** Can we design proteins that are not just stable, but *frustration-free*?
> Using Top7 as a test system, I compare inverse-folding designs from ProteinMPNN with
> multi-objective optimisation that targets energetic frustration directly.

I write software that designs protein sequences against several objectives at once
(Rosetta energy, language-model likelihood, structure-prediction confidence and frustration)
and runs it at scale on MareNostrum 5. I also build plugins for Horus, our group's
workflow platform.

### Research software

**Design**
- **MOOD** (*private for now*): multi-objective genetic algorithm for protein sequence design, with Pareto ranking across all objectives

**Workflows on [Horus](https://github.com/BSC-CNS-EAPM/horus)**
- [protein-set-selection-horus](https://github.com/BSC-CNS-EAPM/protein-set-selection-horus): narrows large design pools down to diverse, high-confidence candidates
- [bioprospecting-horus](https://github.com/BSC-CNS-EAPM/bioprospecting-horus): ProteinMPNN, MAFFT and CodonTransformer as one pipeline

**Simulation and sequence analysis**
- [pele_platform](https://github.com/AlbertCS/pele_platform) and [AdaptivePELE](https://github.com/AlbertCS/AdaptivePELE): Monte Carlo protein–ligand sampling
- [pmx-satumut](https://github.com/AlbertCS/pmx-satumut): free-energy setup for saturation mutagenesis
- [pydca](https://github.com/AlbertCS/pydca): direct coupling analysis for protein and RNA sequences

### Tools I use

<img src="https://skillicons.dev/icons?i=py,r,pytorch,anaconda,bash,linux,docker,git,github,vscode,java,c,cs,latex,md&perline=15" />

Protein design and simulation: PyRosetta · PELE · ProteinMPNN · ESM · ColabFold · BioEmu · frustratometer · SLURM

---
<sub>Based in Barcelona.</sub>
