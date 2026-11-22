#!/usr/bin/env python3
"""Generate bonded-component species maps for the bundled PEO/LiTFSI types."""
import argparse
import json
from collections import Counter
from pathlib import Path
from run_equilibration import read_topology


def generate(data, out, definitions=None):
    _, _, atoms, bonds, _ = read_topology(data)
    remaining = set(atoms)
    molecules = []
    while remaining:
        root = min(remaining)
        remaining.remove(root)
        pending = [root]
        ids = []
        while pending:
            current = pending.pop()
            ids.append(current)
            for neighbor in bonds[current]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        ids.sort()
        types = {int(atoms[i][2]) for i in ids}
        if definitions is None:
            if len(ids) == 1 and types == {1}:
                species = 'Li'
            elif len(ids) == 15 and 2 in types and 1 not in types:
                species = 'TFSI'
            elif len(ids) > 1 and not types.intersection({1, 2}):
                species = 'PEO'
            else:
                raise ValueError(f'Unknown bundled-example component {ids[0]}')
        else:
            matches = [name for name, spec in definitions.items()
                       if types <= set(spec['atom_types'])]
            if len(matches) != 1:
                raise ValueError(f'Component {ids[0]} matches {matches}; provide an explicit species map')
            species = matches[0]
        molecules.append(dict(species=species, atom_ids=ids))
    counts = Counter(m['species'] for m in molecules)
    if definitions is None:
        definitions = {'PEO': {'role': 'polymer'},
                       'Li': {'role': 'cation', 'charge_e': 1},
                       'TFSI': {'role': 'anion', 'charge_e': -1}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(species=definitions, molecules=molecules), indent=2) + '\n')
    print(dict(counts))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--definitions', type=Path, help='JSON species definitions with role, atom_types and ionic charge_e')
    args = parser.parse_args()
    generate(args.data, args.out, json.loads(args.definitions.read_text()) if args.definitions else None)
