import re

pdb_code = '3ixt' # Change for every run
input_file = f'logs/{pdb_code}.log'  # Change for every run
output_file = 'chain_list'
max_iter = 1000

with open(input_file, 'r') as log_file, open(output_file, 'w') as output:
    log_content = log_file.read()

    for i in range(max_iter):
        motif_pattern = f'design_motifscaffolding_{i}'
        motif_pos = log_content.find(motif_pattern)
        if motif_pos == -1:
            break

        timestep_pos = log_content.find('Timestep 3,', motif_pos)
        if timestep_pos == -1:
            break

        rmsd_pos = log_content.find('Sampled motif RMSD: ', timestep_pos)
        if rmsd_pos == -1:
            break

        # Getting RMSD for ith structure
        rmsd_match = re.search(r'Sampled motif RMSD: (\d+\.\d+)', log_content[rmsd_pos:])
        if rmsd_match:
            rmsd_value = float(rmsd_match.group(1))

            # Checking RMSD condition
            if rmsd_value > 1:
                continue

        plddt_pos = log_content.find('pLDDT: ', rmsd_pos)
        if plddt_pos == -1:
            break

        # Getting mean pLDDT for ith structure
        plddt_match = re.search(r'pLDDT: (\d+\.\d+)', log_content[plddt_pos:])
        if plddt_match:
            plddt_value = round(float(plddt_match.group(1)), 2)

            # Checking pLDDT
            if plddt_value >= 0.8:
                output.write(f'{motif_pattern}.pdb\n')
