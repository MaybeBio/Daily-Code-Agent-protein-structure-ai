### Running Monomeric Protein Inference
OpenFold offers an example script that facilitates protein structure inference for single-chain proteins. This script, located at [`/aqlaboratory/openfold/examples/monomer/inference.sh`](https://github.com/aqlaboratory/openfold/examples/monomer/inference.sh), illustrates how to utilize a pretrained OpenFold model to predict the three-dimensional structure of a monomeric protein.

The script configures the inference process by setting several key parameters:
*   **Model Configuration**: It specifies a particular pretrained model architecture, such as the [`model_1_ptm`](https://github.com/aqlaboratory/openfold/tests/config.py#L6) preset. This selection dictates the pre-trained weights and architectural settings employed for the prediction.
*   **Device Targeting**: The script directs the model to execute on a designated CUDA-enabled GPU, which enables accelerated computation.
*   **Reproducibility**: To ensure consistent outcomes, a random seed is set for data processing operations.
*   **Precomputed Alignments**: The script supports the use of precomputed Multiple Sequence Alignments (MSAs). By leveraging existing alignments, the inference process can bypass the time-intensive step of generating them, thereby expediting the prediction workflow. For details on how these alignments are generated, refer to [Advanced Alignment Generation and Processing](#openfold-management-scripts-advanced-alignment-generation-and-processing).

This example serves as a practical guide for users to understand the fundamental steps involved in executing OpenFold for monomeric protein structure prediction.

