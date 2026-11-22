

The OpenFold project is led by a diverse team of researchers and developers from Columbia University and collaborating institutions, bringing together expertise in machine learning, computational biology, and software engineering. This page highlights the key contributors who have made significant impacts on the development and success of OpenFold.

## Primary Leadership

### Mohammed AlQuraishi, PhD
**Position**: Assistant Professor of Systems Biology at Columbia University  
**Role**: Principal Investigator and OpenFold Consortium Lead  

Dr. AlQuraishi is the driving force behind OpenFold, leading the AQ Laboratory at Columbia University where his research focuses on the intersection of machine learning, biophysics, and systems biology. His lab develops machine learning models for predicting protein structure and function, protein-ligand interactions, and learned representations of proteins and proteomes. Dr. AlQuraishi earned his PhD in genetics from Stanford University and holds undergraduate degrees in biology, computer science, and mathematics. Prior to joining Columbia in 2020, he spent time at Harvard Medical School as a Departmental Fellow and Fellow in Systems Pharmacology, where he developed the first end-to-end differentiable model for learning protein structure from data.

His leadership has been instrumental in securing major funding, including grants from the National Institute of General Medical Sciences ([R35GM150546](https://pubmed.ncbi.nlm.nih.gov/38744917/)) and the National Science Foundation, as well as the INCITE 2024 Award. Under his guidance, the AQ Laboratory has become a hub for innovative protein structure prediction research.

## Core Development Team

### Jennifer Wei
**Role**: Lead Developer and Key Contributor  

Jennifer Wei is one of the most active contributors to the OpenFold codebase, as evidenced by her extensive commit history and involvement in critical infrastructure updates. From the recent commit data, Wei has been responsible for numerous important updates, including:

- Merging the PyTorch 2 upgrade in [commit e938c18](https://github.com/aqlaboratory/openfold/commit/e938c184a291bf053af3b14c1e3e8bb29aee57e2)
- Updating dependencies to support numpy 2 and compute capability >9 in [commit da37880](https://github.com/aqlaboratory/openfold/commit/da37880bb7a80f5e8703641110f08187544caebf)
- Supporting OpenMM >8 and fixing tolerance units in amber minimization in [commit 7e06ed9](https://github.com/aqlaboratory/openfold/commit/7e06ed9821926dc6ef5bae54048c813b331b3b58)
- Managing GitHub Actions upgrades and dependency bumps

Wei's work demonstrates deep expertise in software engineering and dependency management, ensuring OpenFold remains compatible with the latest AI/ML frameworks while maintaining stability across different computing environments.

### Sachin Kadyan
**Role**: Research Scientist and Infrastructure Specialist  

Sachin Kadyan is a key developer who has contributed significantly to both the research and practical deployment aspects of OpenFold. His work includes:

- Co-authoring the landmark Nature Methods paper on OpenFold ([DOI: 10.1038/s41592-024-02272-z](https://pubmed.ncbi.nlm.nih.gov/38744917/))
- Leading the development of OpenFold-Multimer and SoloSeq, as mentioned in the [BusinessWire release](https://www.biospace.com/openfold-biotech-ai-research-consortium-releases-soloseq-and-multimer-an-integrated-protein-large-language-model-with-3d-structure-generation)
- Contributing to AWS Batch optimization work, as documented in the [AWS blog post](https://aws.amazon.com/blogs/hpc/optimize-protein-folding-costs-with-openfold-on-aws-batch)

Kadyan's expertise spans from theoretical ML research to practical cloud deployment, making him instrumental in bridging the gap between academic research and industrial applications.

### Christina Floristean
**Role**: Graduate Student and Research Contributor  

Christina Floristean is a graduate student researcher who has made significant contributions to OpenFold's development and research. Her work includes:

- Co-authoring the main OpenFold Nature Methods publication
- Contributing to the development of SoloSeq and OpenFold-Multimer
- Working on protein-ligand co-folding frameworks under Dr. Bouatta's supervision at Harvard

Floristean represents the next generation of researchers in computational structural biology, bringing fresh perspectives and technical expertise to the project.

## Collaborative Ecosystem

The OpenFold project benefits from a broader collaborative ecosystem that includes:

### Nazim Bouatta
**Affiliation**: Senior Research Fellow at Harvard Medical School  
**Contribution**: Co-founder of the OpenFold project and collaborator on research initiatives. Bouatta has been instrumental in securing computational resources and fostering collaborations between Harvard and Columbia teams.

### Industry and Academic Partners
The project has received support from various organizations including:
- **Texas Advanced Computing Center (TACC)**: Providing HPC resources through Frontera and Lonestar6 supercomputers
- **Stability AI**: Contributing compute resources for experiments
- **OpenBioML**: Collaborative support for open-source development
- **NVIDIA**: Providing GPU computing resources

## Research Impact and Publications

The OpenFold team has published extensively in top-tier journals, with their landmark paper ["OpenFold: retraining AlphaFold2 yields new insights into its learning mechanisms and capacity for generalization"](https://pubmed.ncbi.nlm.nih.gov/38744917/) in Nature Methods (August 2024) establishing OpenFold as a critical resource for the protein modeling community. The paper demonstrates that OpenFold matches AlphaFold2's accuracy while providing unprecedented flexibility for training and customization.

## Community Engagement

The contributors actively engage with the scientific community through:
- **Issue Resolution**: Addressing user-reported problems and feature requests
- **Documentation**: Maintaining comprehensive guides for installation and usage
- **Conference Participation**: Presenting at major machine learning and computational biology conferences
- **Open Source Advocacy**: Promoting reproducible science through fully accessible code and training data

## Future Directions

Under the leadership of Dr. AlQuraishi and the core development team, OpenFold continues to evolve with research initiatives focusing on:
- Protein-ligand complex structure prediction
- Single-sequence protein structure prediction
- RNA 3D structure prediction
- Novel neural architectures for improved scalability

The contributors' diverse expertise and collaborative approach ensure that OpenFold remains at the forefront of computational structural biology, driving innovation in protein structure prediction and related fields.