"""Reading a protein language model in its own units: neuron poles, the bases they are compared with, and the tests.

The second version of the interpretability study labels ESMC's feed-forward neurons, each read as a positive and a
negative pole with the gate-closed leak kept apart, and compares them with Haar rotations of the same space, a
randomly initialized model, the residual stream and SAE latents, all sparsified to one firing-rate distribution.
Experiment `2026-11-06_esmc_native_units` holds the preregistration these modules implement.
"""
