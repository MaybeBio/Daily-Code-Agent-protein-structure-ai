"""Sequence design via inverse folding and graph neural network principles (ProteinMPNN-style).

Takes 3D backbone coordinates and target interface context to design amino acid sequences
that stably fold into the scaffold while establishing complementary hydrophobic packing,
salt bridges, and hydrogen bonds against target hotspot residues.
"""

import numpy as np


class ProteinMPNNDesigner:
    """Designs amino acid sequences for generated backbones conditioned on target interface."""

    # Amino acid alphabet and biochemical classes
    HYDROPHOBIC_CORE = ["L", "I", "V", "A", "M"]
    AROMATIC = ["F", "Y", "W"]
    POLAR_SOLVENT = ["E", "K", "R", "Q", "D", "S", "T"]
    TURNS = ["G", "P", "S", "D"]

    def __init__(self, seed=42):
        self.rng = np.random.default_rng(seed)

    def design_sequence(self, scaffold, target_ca_coords, target_res_names, temperature=0.2):
        """Design an amino acid sequence for the scaffold given target interface contacts.

        Args:
            scaffold: MiniProteinBackbone instance
            target_ca_coords: (M, 3) coordinates of target C-alphas
            target_res_names: list of target residue 3-letter names (e.g. ['TYR', 'ASP', ...])
            temperature: sampling temperature (lower = more deterministic/consensus)

        Returns:
            sequence: string of amino acids
            residue_roles: list of roles ('interface', 'core', 'surface', 'turn')
        """
        L = scaffold.length
        sequence = []
        roles = []

        # 1. Compute inter-residue distance matrix inside the scaffold
        internal_dists = np.linalg.norm(
            scaffold.ca_coords[:, None, :] - scaffold.ca_coords[None, :, :], axis=2
        )

        # 2. Compute distance from each scaffold residue to the target
        target_dists = np.linalg.norm(
            scaffold.ca_coords[:, None, :] - target_ca_coords[None, :, :], axis=2
        )
        min_target_dist = np.min(target_dists, axis=1)  # (L,)
        closest_target_idx = np.argmin(target_dists, axis=1)

        # 3. Classify residue microenvironment
        for i in range(L):
            ss = scaffold.secondary_structure[i]
            d_target = min_target_dist[i]
            t_partner_name = target_res_names[closest_target_idx[i]]

            # Number of neighbors within 8.5 Å inside the scaffold (determines burial)
            num_neighbors = np.sum((internal_dists[i] < 8.5) & (internal_dists[i] > 0.1))

            if ss == "T":
                # Turn / Loop region
                role = "turn"
                probs = self._get_turn_probs()
            elif d_target < 8.0:
                # Interface residue contacting target
                role = "interface"
                probs = self._get_interface_probs(t_partner_name)
            elif num_neighbors >= 8:
                # Buried scaffold core
                role = "core"
                probs = self._get_core_probs()
            else:
                # Solvent-exposed surface
                role = "surface"
                probs = self._get_surface_probs()

            # Autoregressive repetition penalty across a 3-residue window
            # Prevents homopolymer runs (e.g., LLLL) and alternating dipeptides (e.g., LILI)
            for lookback, weight in [(1, 0.25), (2, 0.45), (3, 0.70)]:
                if len(sequence) >= lookback:
                    past_aa = sequence[-lookback]
                    if past_aa in probs:
                        probs[past_aa] *= weight

            # Sample amino acid with temperature
            aa = self._sample_with_temperature(probs, temperature)
            sequence.append(aa)
            roles.append(role)

        return "".join(sequence), roles

    def _sample_with_temperature(self, prob_dict, temp=0.2):
        """Apply Boltzmann temperature to probability distribution and sample."""
        aas = list(prob_dict.keys())
        p = np.array(list(prob_dict.values()), dtype=float)

        # Apply temperature
        logits = np.log(np.maximum(p, 1e-12)) / max(temp, 0.01)
        exp_logits = np.exp(logits - np.max(logits))
        p_temp = exp_logits / np.sum(exp_logits)

        return self.rng.choice(aas, p=p_temp)

    def _get_turn_probs(self):
        """Turn/loop preference: flexible, helix-breaking residues."""
        return {
            "G": 0.35, "P": 0.25, "S": 0.15, "D": 0.15, "N": 0.10
        }

    def _get_core_probs(self):
        """Hydrophobic packing core: non-polar side chains."""
        return {
            "L": 0.28, "I": 0.24, "V": 0.22, "A": 0.16, "M": 0.06, "F": 0.04
        }

    def _get_surface_probs(self):
        """Solvent-exposed surface: charged and polar residues to prevent aggregation."""
        return {
            "E": 0.22, "K": 0.22, "R": 0.16, "Q": 0.16, "D": 0.12, "S": 0.06, "T": 0.06
        }

    def _get_interface_probs(self, target_partner_name):
        """Interface residue design complementary to closest target partner."""
        # Aromatic/Hydrophobic target epitope (e.g. Tyr, Phe, Met, Trp, Ile, Val)
        if target_partner_name in ["TYR", "PHE", "TRP", "MET", "ILE", "VAL", "LEU"]:
            # Complement with aromatic stacking and hydrophobic van der Waals contacts
            return {
                "F": 0.25, "L": 0.25, "Y": 0.20, "W": 0.15, "I": 0.10, "A": 0.05
            }
        # Acidic target residue (ASP, GLU)
        elif target_partner_name in ["ASP", "GLU"]:
            # Form salt bridges / polar interactions with basic residues
            return {
                "R": 0.35, "K": 0.35, "Q": 0.15, "N": 0.10, "Y": 0.05
            }
        # Basic target residue (LYS, ARG, HIS)
        elif target_partner_name in ["LYS", "ARG", "HIS"]:
            # Form salt bridges with acidic residues
            return {
                "E": 0.35, "D": 0.35, "Q": 0.15, "N": 0.10, "S": 0.05
            }
        # Polar/Neutral target residue (GLN, ASN, SER, THR)
        else:
            return {
                "Q": 0.25, "N": 0.20, "E": 0.15, "K": 0.15, "Y": 0.15, "L": 0.10
            }
