

OpenFold has seen significant development activity throughout 2025, with major infrastructure upgrades, dependency updates, and ongoing efforts to address technical challenges. This update covers the most recent changes and improvements to the project.

## Major Infrastructure Upgrades

### PyTorch 2 and CUDA 12 Support

The most substantial update in 2025 was the comprehensive upgrade to support **PyTorch 2** and **CUDA 12**, released in April 2025. This upgrade represents a significant milestone for OpenFold's performance and compatibility with modern GPU hardware.

According to the [release notes](https://github.com/aqlaboratory/openfold/releases), the upgrade includes:
- Updated dependency chain to support PyTorch 2.x
- CUDA 12 compatibility for newer GPU architectures
- Support for compute capability >9, enabling use of latest NVIDIA hardware
- Updated NumPy compatibility to support versions >2.0

The upgrade process involved extensive work across multiple components, as evidenced by commits from Jennifer Wei and the development team throughout April 2025. The [environment.yml](https://github.com/aqlaboratory/openfold/commit/da37880bb7a80f5e8703641110f08187544caebf) was modified to `Allow numpy>2 and support compute capability >9`, addressing previous installation issues that users had encountered with NumPy 2.1.0 compatibility.

### Enhanced Documentation and Usability

Alongside the technical upgrades, the team has improved documentation and user experience:
- Fixed inference documentation ([commit](https://github.com/aqlaboratory/openfold/commit/16af434172e95532b056896cc92336810b004674))
- Updated installation docs to build CUDA12 version ([commit](https://github.com/aqlaboratory/openfold/commit/0672517777dea77a09249c89117ab87d3ab57c35))
- Added Open In Colab banner to notebook ([commit](https://github.com/aqlaboratory/openfold/commit/c587b06e8a9655f30112932693c9e715664ebe41))

## Current Technical Challenges

### DeepSpeed Evoformer Attention Issues

A significant ongoing issue affecting OpenFold users involves consistency problems with DeepSpeed evoformer attention when using bfloat16 precision. The [issue #532](https://github.com/aqlaboratory/openfold/issues/532), opened by jnwei in April 2025, highlights several critical problems:

- Unit test `TestDeepSpeedKernel.test_compare_model` fails 30-50% of the time when precision is set to `torch.bfloat16`
- DeepSpeed unit tests fail ~40% of the time when both `bias` term and `bfloat16` are used
- The issue appears to be related to specific attention initialization or input values

The problem extends beyond unit tests, as reported by users experiencing structural prediction issues with longer protein sequences (>256 amino acids) when using bfloat16 precision with DeepSpeed evoformer attention.

### Infrastructure Maintenance

The project continues to receive regular maintenance updates:
- GitHub Actions dependency updates ([commit](https://github.com/aqlaboratory/openfold/commit/ce0029e1199b65fd834fe822be50d936cfe57fd4)) bumping actions/checkout from v4 to v5
- OpenMM support updated to handle versions >8 ([commit](https://github.com/aqlaboratory/openfold/commit/7e06ed9821926dc6ef5bae54048c813b331b3b58))
- Fixed tolerance units in amber minimization ([commit](https://github.com/aqlaboratory/openfold/commit/7e06ed9821926dc6ef5bae54048c813b331b3b58))

## Community and Ecosystem Impact

### Industry Recognition

OpenFold continues to gain recognition in the scientific computing community. According to [NVIDIA's build.nvidia.com](https://build.nvidia.com/openfold/openfold2/modelcard), OpenFold2 is now available as a commercial model, demonstrating its transition from research tool to production-ready solution.

The project has been highlighted for its:
- Accuracy parity with AlphaFold2
- Improved speed characteristics
- Commercial-use licensing under Apache 2.0
- Support for both training and inference workflows

### Research Applications

Recent research continues to leverage OpenFold's unique capabilities. As noted in a [Harvard LSP news article](https://labsyspharm.org/lsp-news/openfold-provides-insights-into-alphafold2s-learning-behavior), OpenFold's open-source nature provides valuable insights into AlphaFold2's learning mechanisms that weren't possible with the original closed-source implementation.

## Development Activity Summary

The development timeline shows sustained activity throughout 2025:

| Period | Focus Area | Key Changes |
|--------|------------|-------------|
| April 2025 | Major Upgrade | PyTorch 2, CUDA 12, NumPy 2 support |
| August 2025 | Maintenance | GitHub Actions updates, dependency management |
| September 2025 | Issue Resolution | Ongoing bfloat16 consistency investigations |

The project maintains active development with contributions from core team members like Jennifer Wei, who has been instrumental in driving the PyTorch 2 upgrade and various infrastructure improvements.

Looking ahead, the team appears focused on resolving the DeepSpeed bfloat16 consistency issues while continuing to maintain and improve the core infrastructure that makes OpenFold a vital tool in the protein structure prediction ecosystem.