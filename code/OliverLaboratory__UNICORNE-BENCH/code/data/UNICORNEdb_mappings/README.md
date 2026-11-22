Mapping CSVs for UNICORNEdb

pdbs-mapped-6-12-23-2025.csv: Monomeric ensembles grouped by uniprot - follows format: {uniprotID},{pdbID1}_{chainID1}:{resIDs};{pdbID2}_{chainID2}:{resIDs} ... (resIDs can be 'full' when entire chain is included, or have format {start_pos}-{end_pos} when a only a segment spanning a certain range of resIDs are included, or {start_pos1}-{end_pos1}!{start_pos2}-{end_pos2} when multiple separate segments are contained in one structure)

pdbs-mapped-oligomers-diff-12-23-2025.csv: Oligomeric ensembles grouped by uniprot - follows same format as pdbs-mapped-6-12-23-2025.csv, includes oligomeric and monomeric structures, differentiated by the names of the associated .cif files

ecod-folds-3-12-23-2025.csv: groupings of ensembles by fold as determined by ECOD topology - follows format: {fold},{uniprotID1}:{pdbID1}_{chainID1}_{resID_start_pos1}-{resID_end_pos1};{pdbID2}_{chainID2}_{resID_start_pos2}-{resID_end_pos2}"{uniprotID2}:...

interpro-domains-full-12-23-2025.csv: groupings of ensembles by fold/domain pairing as determined by ECOD topology and InterPro domain - follows format: {fold},{domain},{uniprotID1}:{pdbID1}_{chainID1}_{resID_start_pos1}-{resID_end_pos1};{pdbID2}_{chainID2}_{resID_start_pos2}-{resID_end_pos2}"{uniprotID2}:... (same format as ecod-folds-3-12-23-2025.csv with added column for {domain} between fold column and list of uniprots
