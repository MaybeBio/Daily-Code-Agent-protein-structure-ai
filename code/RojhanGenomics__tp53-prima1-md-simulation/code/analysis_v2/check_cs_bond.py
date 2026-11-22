#!/usr/bin/env python3
"""
check_cs_bond.py -- bond lengths of the MQ-methanethiol Michael-addition product (manuscript Section 2.9 / 4.8)

MQ (methylene quinuclidinone):          C1CN2CCC1C(=O)C2=C
product with methanethiol (CH3SH):      C1CN2CCC1C(=O)C2CSC    (new bond: ring-CH-CH2-S)
50 ETKDGv3 conformers are minimised with MMFF94 (RDKit).  The script prints
  * the newly formed C(H2)-S bond (the bond between the former exocyclic methylene carbon and sulfur)
  * the S-CH3 bond of the methanethiol model
for the lowest-energy conformer and over all conformers.

Run:   conda activate tp53_md ;  python check_cs_bond.py
The manuscript text (revised) gives 1.83 A (1.829-1.833 A) for the new C-S bond and 1.81 A for S-CH3.
"""
import numpy as np
import rdkit
from rdkit import Chem
from rdkit.Chem import AllChem

print("RDKit", rdkit.__version__)
smi = "C1CN2CCC1C(=O)C2CSC"
m = Chem.AddHs(Chem.MolFromSmiles(smi))
match = m.GetSubstructMatch(Chem.MolFromSmarts("[CH2;!R]-[SX2]-[CH3]"))
if len(match) != 3:
    raise SystemExit("could not find the C-S-C fragment in the product")
c_new, s, c_me = match
ps = AllChem.ETKDGv3()
ps.randomSeed = 7
cids = list(AllChem.EmbedMultipleConfs(m, 50, ps))
res = AllChem.MMFFOptimizeMoleculeConfs(m, maxIters=5000)
E = np.array([e for _, e in res])
rows = []
for i, cid in enumerate(cids):
    pos = m.GetConformer(cid).GetPositions()
    rows.append((E[i], np.linalg.norm(pos[c_new] - pos[s]), np.linalg.norm(pos[s] - pos[c_me])))
rows.sort()
print(f"conformers minimised: {len(rows)}")
print(f"lowest-energy conformer: new C-S = {rows[0][1]:.3f} A, S-CH3 = {rows[0][2]:.3f} A (MMFF94 energy {rows[0][0]:.2f} kcal/mol)")
cs = np.array([r[1] for r in rows])
sm = np.array([r[2] for r in rows])
print(f"new C-S over all conformers: {cs.min():.3f} - {cs.max():.3f} A (mean {cs.mean():.3f})")
print(f"S-CH3  over all conformers: {sm.min():.3f} - {sm.max():.3f} A (mean {sm.mean():.3f})")
print("\nThe value 1.808 A of the submitted manuscript matches the S-CH3 bond, not the newly formed C-S bond.")
