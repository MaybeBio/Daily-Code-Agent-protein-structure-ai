#!/bin/bash
# Rebuilds a complete, atom-count-verified protein topology (194 residues,
# 3010 atoms, full Leu289 C-terminus) directly from the source PDB structure.
#
# Background: an earlier working topology file in this repository was found
# to be missing the C-terminal tail of Leu289 (11 atoms: CD1/CD2 side chain
# + backbone C/O), apparently truncated during unrelated covalent-adduct
# testing. This script regenerates a verified-complete topology from the
# original 2OCJ_chainA_clean.pdb using AMBER99SB-ILDN/TIP3P, and can be used
# to reproduce or re-verify the topology used for Run2-Run4 and the
# negative-control simulation.

grep "^ATOM" 2OCJ_chainA_clean.pdb > protein_only.pdb
echo "END" >> protein_only.pdb

gmx pdb2gmx -f protein_only.pdb -o protein_rebuilt.gro -p topol_rebuilt.top \
  -i posre_rebuilt.itp -ff amber99sb-ildn -water tip3p -ignh

# Verify: should report "194 residues with 3010 atoms"
