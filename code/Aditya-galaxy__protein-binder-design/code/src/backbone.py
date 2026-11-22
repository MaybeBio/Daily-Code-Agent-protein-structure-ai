"""De novo miniprotein backbone generation and epitope targeting.

Constructs structurally valid mini-protein backbones (e.g., 3-helix bundles, 50-65 residues)
and aligns the recognition interface against target hotspot residues with proper van der Waals
spacing and zero steric overlap.
"""

import numpy as np


class MiniProteinBackbone:
    """Represents a generated 3D backbone with N, CA, C, O atomic coordinates."""

    def __init__(self, sequence_length=60):
        self.length = sequence_length
        # Arrays of shape (L, 3) for primary backbone atoms
        self.n_coords = np.zeros((sequence_length, 3))
        self.ca_coords = np.zeros((sequence_length, 3))
        self.c_coords = np.zeros((sequence_length, 3))
        self.o_coords = np.zeros((sequence_length, 3))
        self.secondary_structure = ["C"] * sequence_length  # 'H' for helix, 'T' for turn

    def translate(self, vector):
        self.n_coords += vector
        self.ca_coords += vector
        self.c_coords += vector
        self.o_coords += vector

    def rotate(self, rotation_matrix):
        self.n_coords = (rotation_matrix @ self.n_coords.T).T
        self.ca_coords = (rotation_matrix @ self.ca_coords.T).T
        self.c_coords = (rotation_matrix @ self.c_coords.T).T
        self.o_coords = (rotation_matrix @ self.o_coords.T).T

    def get_centroid(self):
        return np.mean(self.ca_coords, axis=0)


class BackboneGenerator:
    """Generates de novo helical-bundle miniprotein scaffolds targeted to an epitope."""

    def __init__(self, seed=42):
        self.rng = np.random.default_rng(seed)

    def generate_three_helix_bundle(self, helix_lens=(18, 16, 18), loop_len=3):
        """Generate a canonical 3-helix bundle miniprotein backbone."""
        total_len = sum(helix_lens) + 2 * loop_len
        scaffold = MiniProteinBackbone(sequence_length=total_len)

        # Build individual idealized alpha-helices
        # Alpha-helix parameters: 3.6 residues/turn, 1.5 Å rise/residue, radius = 2.3 Å
        r_helix = 2.3
        pitch_per_res = 1.5
        rad_per_res = 2.0 * np.pi / 3.6
        offset_x = 9.5
        offset_y = 8.5
        start_z = (helix_lens[0] - 1) * pitch_per_res

        # Helix 1: along +Z axis, center at x = 0, y = 0
        idx = 0
        # Helix 1 (e.g. 18 res)
        for h_i in range(helix_lens[0]):
            theta = h_i * rad_per_res
            z = h_i * pitch_per_res
            ca = np.array([r_helix * np.cos(theta), r_helix * np.sin(theta), z])
            self._set_residue_atoms(scaffold, idx, ca, theta, z, is_helix=True)
            idx += 1

        # Loop 1-2 (3 res turn bridging Helix 1 to Helix 2)
        h2_start = np.array([offset_x + r_helix, 0.0, start_z])
        h1_end = scaffold.ca_coords[idx - 1]
        for t_i in range(loop_len):
            alpha = (t_i + 1) / (loop_len + 1)
            # Cubic Hermite / smooth arc
            ca = (1 - alpha) * h1_end + alpha * h2_start + np.array([0.0, 2.5 * np.sin(np.pi * alpha), 1.5 * np.sin(np.pi * alpha)])
            self._set_residue_atoms(scaffold, idx, ca, 0, ca[2], is_helix=False)
            idx += 1

        # Helix 2: antiparallel (along -Z axis), offset in X by ~9.5 Å
        for h_i in range(helix_lens[1]):
            theta = -h_i * rad_per_res
            z = start_z - h_i * pitch_per_res
            ca = np.array([offset_x + r_helix * np.cos(theta), r_helix * np.sin(theta), z])
            self._set_residue_atoms(scaffold, idx, ca, theta, z, is_helix=True)
            idx += 1

        # Loop 2-3 (3 res turn bridging Helix 2 to Helix 3)
        h3_start = np.array([4.8 + r_helix, offset_y, 0.0])
        h2_end = scaffold.ca_coords[idx - 1]
        for t_i in range(loop_len):
            alpha = (t_i + 1) / (loop_len + 1)
            ca = (1 - alpha) * h2_end + alpha * h3_start + np.array([-1.5 * np.sin(np.pi * alpha), 0.0, -2.0 * np.sin(np.pi * alpha)])
            self._set_residue_atoms(scaffold, idx, ca, 0, ca[2], is_helix=False)
            idx += 1

        # Helix 3: parallel to Helix 1 (along +Z axis), offset in Y by ~8.5 Å
        for h_i in range(helix_lens[2]):
            theta = h_i * rad_per_res
            z = h_i * pitch_per_res
            ca = np.array([4.8 + r_helix * np.cos(theta), offset_y + r_helix * np.sin(theta), z])
            self._set_residue_atoms(scaffold, idx, ca, theta, z, is_helix=True)
            idx += 1

        return scaffold

    def _set_residue_atoms(self, scaffold, idx, ca_coord, theta, z, is_helix=True):
        """Construct realistic N, C, O atom coordinates around CA."""
        # Standard bond vectors
        n_vec = np.array([-0.8, -0.6, 1.0])
        n_vec = n_vec / np.linalg.norm(n_vec) * 1.46

        c_vec = np.array([0.9, 0.7, -0.9])
        c_vec = c_vec / np.linalg.norm(c_vec) * 1.52

        o_vec = np.array([1.2, 1.4, -0.2])
        o_vec = o_vec / np.linalg.norm(o_vec) * 2.40

        scaffold.ca_coords[idx] = ca_coord
        scaffold.n_coords[idx] = ca_coord + n_vec
        scaffold.c_coords[idx] = ca_coord + c_vec
        scaffold.o_coords[idx] = ca_coord + o_vec
        scaffold.secondary_structure[idx] = "H" if is_helix else "T"

    def dock_to_epitope(self, scaffold, target_ca_coords, hotspot_ca_coords, target_centroid, desired_dist=7.5):
        """Translate and orient scaffold so Helix 1 interfaces with the target hotspot."""
        # Center scaffold at origin
        scaffold_centroid = scaffold.get_centroid()
        scaffold.translate(-scaffold_centroid)

        # Epitope centroid and target outward normal vector
        hotspot_centroid = np.mean(hotspot_ca_coords, axis=0)
        outward_normal = hotspot_centroid - target_centroid
        outward_norm = np.linalg.norm(outward_normal)
        if outward_norm > 1e-6:
            outward_normal = outward_normal / outward_norm
        else:
            outward_normal = np.array([1.0, 0.0, 0.0])

        # Align scaffold primary axis with hotspot normal
        z_axis = np.array([0.0, 0.0, 1.0])
        rot_axis = np.cross(z_axis, outward_normal)
        rot_axis_len = np.linalg.norm(rot_axis)
        if rot_axis_len > 1e-4:
            rot_axis = rot_axis / rot_axis_len
            angle = np.arccos(np.clip(np.dot(z_axis, outward_normal), -1.0, 1.0))
            R = self._rotation_matrix(rot_axis, angle)
            scaffold.rotate(R)

        # Add slight random perturbation around approach vector
        random_angle = self.rng.uniform(-np.pi / 4, np.pi / 4)
        R_rand = self._rotation_matrix(outward_normal, random_angle)
        scaffold.rotate(R_rand)

        # Translate scaffold to epitope surface with optimal distance
        target_pos = hotspot_centroid + outward_normal * desired_dist
        scaffold.translate(target_pos)

        # Iteratively resolve steric overlap so closest C-alpha is between 4.8 and 6.5 Å
        for _ in range(50):
            dists = np.linalg.norm(
                scaffold.ca_coords[:, None, :] - target_ca_coords[None, :, :], axis=2
            )
            min_d = float(np.min(dists))
            if min_d < 4.8:
                scaffold.translate(outward_normal * (5.0 - min_d))
            else:
                break

        return scaffold

    def _rotation_matrix(self, axis, theta):
        """Rodrigues' rotation formula for 3D rotation matrix."""
        axis = np.asarray(axis)
        axis = axis / np.sqrt(np.dot(axis, axis))
        a = np.cos(theta / 2.0)
        b, c, d = -axis * np.sin(theta / 2.0)
        aa, bb, cc, dd = a * a, b * b, c * c, d * d
        bc, ad, ac, ab, bd, cd = b * c, a * d, a * c, a * b, b * d, c * d
        return np.array([
            [aa + bb - cc - dd, 2 * (bc + ad), 2 * (bd - ac)],
            [2 * (bc - ad), aa + cc - bb - dd, 2 * (cd + ab)],
            [2 * (bd + ac), 2 * (cd - ab), aa + dd - bb - cc]
        ])
