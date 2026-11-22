"""End-to-end De Novo Protein Binder Design Pipeline.

Orchestrates backbone generation, inverse folding sequence design, biophysical
validation, and lead candidate export.
"""

import json
import os
import numpy as np
import matplotlib.pyplot as plt

from .target import TargetHandler
from .backbone import BackboneGenerator
from .mpnn import ProteinMPNNDesigner
from .geometry import interface_geometry, rank_key


class DeNovoBinderPipeline:
    """End-to-end campaign orchestrator for de novo protein binders."""

    def __init__(self, target_pdb, target_chain="A", seed=42):
        self.target_pdb = target_pdb
        self.target_chain = target_chain
        self.seed = seed
        self.target_handler = TargetHandler(target_pdb, target_chain=target_chain)
        self.backbone_gen = BackboneGenerator(seed=seed)
        self.mpnn_designer = ProteinMPNNDesigner(seed=seed)

    def run_campaign(
        self,
        hotspot_res_nums=None,
        partner_chain="B",
        num_backbones=15,
        seqs_per_backbone=2,
        output_dir="results",
    ):
        """Execute a full generative binder design campaign."""
        os.makedirs(output_dir, exist_ok=True)
        print("=" * 70)
        print("  DE NOVO PROTEIN BINDER DESIGN PIPELINE")
        print("=" * 70)

        # 1. Epitope Hotspot Definition
        if hotspot_res_nums is None:
            print(f"Detecting biological hotspot residues from complex partner chain '{partner_chain}'...")
            hotspots = self.target_handler.find_hotspots_from_complex(partner_chain=partner_chain, cutoff=4.5)
            hotspot_res_nums = [h["res_num"] for h in hotspots]
            print(f"  Identified {len(hotspot_res_nums)} hotspot residues on Chain {self.target_chain}:")
            preview = [f"{h['res_name']}{h['res_num']}" for h in hotspots[:8]]
            print(f"  {preview} ...")
        else:
            print(f"Using {len(hotspot_res_nums)} user-specified hotspot residues.")

        # Target coordinates and centroid
        target_ca = self.target_handler.ca_coords
        target_centroid = np.mean(target_ca, axis=0)
        hotspot_ca = np.array([
            r["CA"].coord for r in self.target_handler.residues if r.id[1] in hotspot_res_nums and "CA" in r
        ])
        target_res_names = [r.resname for r in self.target_handler.residues if "CA" in r]

        # 2. Generative Backbone Generation & Sequence Design
        print(f"\nGenerating {num_backbones} de novo backbones x {seqs_per_backbone} sequences = {num_backbones * seqs_per_backbone} designs...")
        candidates = []

        candidate_id = 1
        for b_i in range(num_backbones):
            # Vary helix lengths slightly to sample diverse bundle topologies
            h1 = 18 + (b_i % 3)
            h2 = 15 + ((b_i + 1) % 3)
            h3 = 17 + ((b_i + 2) % 3)
            scaffold = self.backbone_gen.generate_three_helix_bundle(helix_lens=(h1, h2, h3))

            # Dock scaffold against target epitope
            desired_dist = 6.8 + (b_i % 4) * 0.4
            self.backbone_gen.dock_to_epitope(
                scaffold, target_ca, hotspot_ca, target_centroid, desired_dist=desired_dist
            )

            # Design sequences with MPNN
            for s_i in range(seqs_per_backbone):
                temp = 0.15 if s_i == 0 else 0.35
                seq, roles = self.mpnn_designer.design_sequence(
                    scaffold, target_ca, target_res_names, temperature=temp
                )

                # Measure the interface. This describes an arrangement; it does not validate it.
                metrics = interface_geometry(scaffold.ca_coords, target_ca, hotspot_ca)

                candidates.append({
                    "design_id": f"binder_{candidate_id:03d}",
                    "backbone_idx": b_i,
                    "sequence": seq,
                    "length": scaffold.length,
                    "scaffold": scaffold,
                    "roles": roles,
                    "metrics": metrics,
                })
                candidate_id += 1

        # 3. Order for inspection. Not a quality ranking: see geometry.rank_key.
        candidates.sort(key=lambda c: rank_key(c["metrics"]))
        top_lead = candidates[0]

        # 4. Save Summary Table
        print("\n" + "=" * 78)
        print(f"{'Design ID':<12} | {'Interface res':<13} | {'Hotspots':<9} | {'Min CA (A)':<10} | {'Clashes'}")
        print("=" * 78)
        for c in candidates[:8]:
            m = c["metrics"]
            hot = f"{m.get('hotspots_engaged', 0)}/{m.get('hotspots_total', 0)}"
            print(f"{c['design_id']:<12} | {m['interface_residues']:<13d} | {hot:<9} | "
                  f"{m['min_ca_distance_angstrom']:<10.2f} | {m['ca_clashes']}")
        print("=" * 78)
        print("Geometry only. No folding or binding prediction is made: see README section 3.")

        # 5. Export Artifacts
        self._export_complex_pdb(top_lead, os.path.join(output_dir, "top_lead_complex.pdb"))
        self._export_pymol_script(top_lead, hotspot_res_nums, os.path.join(output_dir, "view_binder_complex.pml"))
        self._plot_contact_map(top_lead, target_ca, os.path.join(output_dir, "binder_contact_map.png"))

        # Save JSON metadata (excluding scaffold object for JSON serialization)
        serializable_results = []
        for c in candidates:
            item = {k: v for k, v in c.items() if k != "scaffold"}
            serializable_results.append(item)

        with open(os.path.join(output_dir, "design_summary.json"), "w") as f:
            json.dump({
                "target_pdb": self.target_pdb,
                "target_chain": self.target_chain,
                "hotspot_residues": hotspot_res_nums,
                "total_designs": len(candidates),
                "top_lead_id": top_lead["design_id"],
                "top_lead_metrics": top_lead["metrics"],
                "candidates": serializable_results,
            }, f, indent=2)

        print(f"\nTop Lead Candidate: {top_lead['design_id']}")
        print(f"  Sequence: {top_lead['sequence']}")
        _m = top_lead["metrics"]
        print(f"  Interface residues: {_m['interface_residues']} | "
              f"hotspots engaged: {_m.get('hotspots_engaged', 0)}/{_m.get('hotspots_total', 0)} | "
              f"closest CA pair: {_m['min_ca_distance_angstrom']:.2f} A | clashes: {_m['ca_clashes']}")
        print("  Whether it folds or binds is unknown and untested.")
        print(f"\nGenerated files in '{output_dir}/':")
        print(f"  • top_lead_complex.pdb")
        print(f"  • binder_contact_map.png")
        print(f"  • view_binder_complex.pml")
        print(f"  • design_summary.json")

        return top_lead

    def _export_complex_pdb(self, candidate, output_path):
        """Write PDB with Target as Chain A and Designed Binder as Chain B."""
        scaffold = candidate["scaffold"]
        seq = candidate["sequence"]

        aa_3letter = {
            "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE",
            "G": "GLY", "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU",
            "M": "MET", "N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG",
            "S": "SER", "T": "THR", "V": "VAL", "W": "TRP", "Y": "TYR"
        }

        with open(output_path, "w") as f:
            # Write target residues (Chain A)
            atom_num = 1
            for r in self.target_handler.residues:
                for a in r.get_atoms():
                    if a.element == "H":
                        continue
                    coord = a.coord
                    line = f"ATOM  {atom_num:5d}  {a.name:<4s}{r.resname:>3s} A{r.id[1]:4d}    {coord[0]:8.3f}{coord[1]:8.3f}{coord[2]:8.3f}  1.00 20.00           {a.element:>2s}\n"
                    f.write(line)
                    atom_num += 1

            f.write("TER\n")

            # Write binder residues (Chain B)
            for i in range(scaffold.length):
                res_3 = aa_3letter.get(seq[i], "ALA")
                res_id = i + 1
                atoms = [
                    ("N", scaffold.n_coords[i], "N"),
                    ("CA", scaffold.ca_coords[i], "C"),
                    ("C", scaffold.c_coords[i], "C"),
                    ("O", scaffold.o_coords[i], "O"),
                ]
                for a_name, coord, elem in atoms:
                    line = f"ATOM  {atom_num:5d}  {a_name:<4s}{res_3:>3s} B{res_id:4d}    {coord[0]:8.3f}{coord[1]:8.3f}{coord[2]:8.3f}  1.00  0.00           {elem:>2s}\n"
                    f.write(line)
                    atom_num += 1

            f.write("TER\nEND\n")

    def _export_pymol_script(self, candidate, hotspots, output_path):
        """Generate PyMOL visualization script."""
        hotspot_str = "+".join(str(h) for h in hotspots)
        content = f"""# PyMOL script: De Novo Protein Binder Complex
load results/top_lead_complex.pdb, complex
hide everything, complex
show cartoon, complex

# Color chains
color white, chain A               # Target (e.g. PD-L1)
color deepsalmon, chain B          # De Novo Designed Binder

# Highlight target hotspot epitope
select target_hotspots, chain A and resi {hotspot_str}
show sticks, target_hotspots
color marine, target_hotspots and name C*

# Highlight binder interface contacts (< 5.0 Å)
select binder_interface, chain B within 5.0 of chain A
show sticks, binder_interface
color firebrick, binder_interface and name C*

# Show interface polar contacts
distance interface_hbonds, target_hotspots, binder_interface, mode=2
set dash_color, yellow, interface_hbonds
set dash_width, 2.5, interface_hbonds

zoom chain B, 6.0
set ray_shadow, 0
bg_color white
"""
        with open(output_path, "w") as f:
            f.write(content)

    def _plot_contact_map(self, candidate, target_ca, output_path):
        """Plot inter-chain contact distance map."""
        scaffold_ca = candidate["scaffold"].ca_coords
        dists = np.linalg.norm(scaffold_ca[:, None, :] - target_ca[None, :, :], axis=2)

        plt.figure(figsize=(8, 6), dpi=300)
        plt.imshow(dists, cmap="viridis_r", vmin=3.0, vmax=25.0, aspect="auto")
        cbar = plt.colorbar()
        cbar.set_label("Cα - Cα Distance (Å)", fontsize=11)

        plt.title(f"Inter-Chain Contact Map: {candidate['design_id']} vs Target", fontsize=12, fontweight="bold")
        plt.xlabel("Target Residue Index (Chain A)", fontsize=11)
        plt.ylabel("Designed Binder Residue Index (Chain B)", fontsize=11)
        plt.tight_layout()
        plt.savefig(output_path)
        plt.close()
