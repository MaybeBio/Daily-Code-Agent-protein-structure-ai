"""The experimental annotation release: assertions with experimental support, split by homology, one train-fitted vocabulary.

Each module reads one source (GOA, UniProtKB XML, InterPro) into `Assertion` rows, `pool` joins them per sequence, and
`vocabulary`, `release` and `acceptance` turn the pool and its split into the Hub release. The order of a build is
`pipeline.run_build`, and the choices behind it are in the project's decision records.
"""
