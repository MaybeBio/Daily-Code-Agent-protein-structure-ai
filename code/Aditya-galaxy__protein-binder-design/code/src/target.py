"""Target preprocessing and epitope hotspot identification.

Handles target PDB ingestion, solvent removal, chain extraction, and identification
of functionally critical binding epitope residues (hotspots).
"""

import numpy as np
from Bio.PDB import PDBParser, PDBIO, Select


class NonWaterSelect(Select):
    """Filter out water molecules and non-protein heteroatoms."""
    def __init__(self, target_chain_id):
        self.target_chain_id = target_chain_id

    def accept_chain(self, chain):
        return chain.id == self.target_chain_id

    def accept_residue(self, residue):
        # Keep only standard amino acid residues (hetero flag == ' ')
        return residue.id[0] == " "


class TargetHandler:
    """Manages target structure analysis and epitope hotspot definition."""

    def __init__(self, pdb_path, target_chain="A"):
        self.pdb_path = pdb_path
        self.target_chain = target_chain
        parser = PDBParser(QUIET=True)
        self.structure = parser.get_structure("target", pdb_path)
        self.model = self.structure[0]
        self.chain = self.model[target_chain]
        self._cache_residues()

    def _cache_residues(self):
        """Cache standard protein residues and CA coordinates."""
        self.residues = [r for r in self.chain.get_residues() if r.id[0] == " "]
        self.ca_coords = np.array([r["CA"].coord for r in self.residues if "CA" in r])
        self.res_ids = [r.id[1] for r in self.residues if "CA" in r]

    def find_hotspots_from_complex(self, partner_chain="B", cutoff=4.5):
        """Identify target residues contacting a biological partner chain within cutoff distance."""
        if partner_chain not in self.model:
            raise ValueError(f"Partner chain '{partner_chain}' not found in structure.")

        partner = self.model[partner_chain]
        partner_atoms = [
            a for r in partner.get_residues() if r.id[0] == " "
            for a in r.get_atoms() if a.element != "H"
        ]
        partner_coords = np.array([a.coord for a in partner_atoms])

        hotspots = []
        for r in self.residues:
            target_atoms = [a for a in r.get_atoms() if a.element != "H"]
            if not target_atoms:
                continue
            t_coords = np.array([a.coord for a in target_atoms])
            # Minimum distance between any target atom and any partner atom
            dists = np.linalg.norm(t_coords[:, None, :] - partner_coords[None, :, :], axis=2)
            min_dist = float(np.min(dists))

            if min_dist <= cutoff:
                hotspots.append({
                    "res_num": r.id[1],
                    "res_name": r.resname,
                    "ca_coord": r["CA"].coord.tolist() if "CA" in r else None,
                    "min_distance_to_partner": round(min_dist, 2)
                })

        hotspots.sort(key=lambda x: x["res_num"])
        return hotspots

    def get_epitope_center(self, hotspot_res_nums):
        """Compute the geometric centroid of the specified hotspot residues."""
        coords = []
        for r in self.residues:
            if r.id[1] in hotspot_res_nums and "CA" in r:
                coords.append(r["CA"].coord)

        if not coords:
            raise ValueError("No matching hotspot CA coordinates found.")
        return np.mean(coords, axis=0)

    def save_clean_target(self, output_path):
        """Export clean target chain PDB without heteroatoms or solvent."""
        io = PDBIO()
        io.set_structure(self.structure)
        io.save(output_path, select=NonWaterSelect(self.target_chain))
