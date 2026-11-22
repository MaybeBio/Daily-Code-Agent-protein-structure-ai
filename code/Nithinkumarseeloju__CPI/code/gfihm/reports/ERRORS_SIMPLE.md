# Errors and warnings explained simply

The input files were not changed. An exclusion means this pipeline did not use that example for training; it does not prove the original experiment is wrong.

| Problem | Complexes | Simple explanation |
|---|---:|---|
| INDEX_FLAGS_INCOMPLETE_STRUCTURE | 548 | The index says part of the structure is missing. Like a puzzle with missing pieces, it should not be used as a complete training example. |
| INDEX_FLAGS_COVALENT_COMPLEX | 644 | The compound makes a chemical bond to the protein. It needs special handling, so it is outside this ordinary noncovalent training set. |
| CENSORED_OR_UNPARSEABLE_AFFINITY | 270 | The score is a limit, such as less than 10, rather than one exact answer. It was kept for viewing but not treated as an exact training answer. |
| SEVERE_PROTEIN_LIGAND_CLASH | 222 | Some protein and compound atoms are less than 1 angstrom apart. They appear to overlap, so this example needs checking. |
| DISCONNECTED_LIGAND | 63 | The ligand file contains separate pieces that are not joined by chemical bonds. A reviewer must decide which pieces belong to the compound. |
| LIGAND_CHEMISTRY_INVALID_IN_SDF_AND_MOL2 | 2 | RDKit cannot accept the chemical structure in either ligand file. The saved atom and bond description needs correction. |

A complex may have more than one problem, so these counts must not be added together.

**Two failed complex IDs: 3vjs and 3vjt.** Their ligand chemistry fails in both SDF and MOL2. Exact RDKit messages are saved in `failed_ligand_diagnostics.json`. They have no output graph.

Other warnings:

- 1lvk: the SDF reader failed, but the MOL2 file worked. Its graph was recovered using MOL2.
- 101 complexes: the ligand partial-charge calculation was unavailable. The values are marked unknown using a mask; they are not claimed to be neutral. See the manifest for IDs.
- 8,231 complexes: separate ions or cofactors were omitted from the protein pocket graph. Those groups can matter biologically. The original full protein files remain in the archive.
- All protein partial charges and protein chemical bond orders are unassigned. Distance connections are saved instead. This is not a simulation-ready force-field topology.

| CSV dataset | Duplicate rows removed | Rows with conflicting scores set aside |
|---|---:|---:|
| Davis | 1,936 | 2,894 |
| Kiba | 185 | 700 |
| Metz | 0 | 0 |

A duplicate is the same compound, same protein and same score written more than once. A conflict is the same compound and protein with different scores. Different experiments may produce different values; because this CSV has no experiment IDs, conditions or units, conflicting rows were set aside rather than averaged. Every removed row has its original CSV line number in `processed/<dataset>/excluded_rows.csv`.

**Model code recovered:** the archive lacked source code, but the original code was found in `H:/siddu/perceiver_gpu/model_2d` and copied to `model_source/`. All three score models now run. They read 2D compound features and protein sequences; the XYZ graph files belong to a separate 3D workflow.

**Missing 3D information in Davis, KIBA and Metz:** their CSVs contain SMILES, protein sequences and numbers. A sequence is a list of building blocks; it does not tell us the measured position of every atom or where the compound sits. No binding poses were invented for these rows.

**Motion:** the viewer moves the compound along an artificial path to explain the bound pose. It is not a real movie of binding. A physical simulation requires additional preparation and computation.

Exact chemistry error for both failed complexes: `Explicit valence for atom # 0 B, 5, is greater than permitted`. In simple words: the file gives a boron atom a bond arrangement this chemistry checker does not accept. This might need a corrected representation or specialist handling of boron chemistry; the automated result alone does not prove the experiment is wrong.

## Website messages

- **No verified structure:** we know the compound text and protein letters, but we cannot confirm their joint 3D shape from the supplied files. The score can still run. The viewer stays empty rather than showing a different pair.
- **No checked approach:** the final structure exists, but the compound would pass through protein atoms along the paths tested. You can inspect the final pose, but Play is disabled.
- **Contact names unavailable:** the contact tool could not prepare the compound correctly (40 of 50 analyzed structures). We can still show which atoms are near each other, but we cannot safely call those distances hydrogen bonds.
- **3vjs and 3vjt rejected:** their boron bond descriptions were not accepted by the chemistry checker. Keep the originals and ask for a corrected chemical representation.
- **Protein too long for this score model:** the original model keeps only the first 500 tokens. The page tells you when this happens. The shown structural domain can lie outside that part of the sequence.
- **Scores differ slightly from saved results:** fresh predictions work, but historical batch checks missed the strict 0.0001 tolerance. We have not proved identical numerical reproduction.
- **Docking failed:** the receptor or compound preparation may not be supported. The page links the exact job error and allows retry. A docking score is separate from the trained model score.

All original CSV measurements, including conflicting scores, are retained in the website catalog. Removed/set-aside counts above describe only the separate filtered training CSVs. No physical binding simulation has been produced.
