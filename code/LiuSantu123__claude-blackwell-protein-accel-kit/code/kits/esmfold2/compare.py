"""Compare completed ESMFold2 runs on identical inputs and settings."""

import argparse
import json
from pathlib import Path

import numpy as np


def compare(before, after):
    base, test = [json.loads((path / 'summary.json').read_text()) for path in (before, after)]
    if not (base['finished'] and test['finished']):
        raise ValueError('both runs must be marked finished')
    for key in ('settings', 'model', 'esmc', 'esmc_precision', 'gpu', 'esm', 'torch', 'triton'):
        if base[key] != test[key]:
            raise ValueError(f'run mismatch: {key}')
    baseline = {row['design']: row for row in base['results']}
    candidate = {row['design']: row for row in test['results']}
    if baseline.keys() != candidate.keys():
        raise ValueError('the runs must contain the same designs')
    report = []
    for name, a in baseline.items():
        b = candidate[name]
        if a['inputs'] != b['inputs']:
            raise ValueError(f'{name}: input fingerprint mismatch')
        row = dict(design=name, baseline_status=a['status'], candidate_status=b['status'])
        if a['status'] == b['status'] == 'ok':
            if a['feature_msa_rows'] != b['feature_msa_rows'] or a['chain_order'] != b['chain_order']:
                raise ValueError(f'{name}: model input and/or confidence axes differ')
            with (np.load(before / a['confidence']) as ca, np.load(after / b['confidence']) as cb):
                for key in ('token_chain_ids', 'residue_index'):
                    if not np.array_equal(ca[key], cb[key]):
                        raise ValueError(f'{name}: mismatched {key}')
                row['mean_abs_pae_delta_angstrom'] = float(np.abs(cb['pae'] - ca['pae']).mean())
                row['chain_order'] = b['chain_order']
                row['pair_chains_iptm_delta'] = (cb['pair_chains_iptm'] - ca['pair_chains_iptm']).tolist()
            row['speedup'] = a['seconds'] / b['seconds']
            for key in ('iptm', 'ptm', 'seconds', 'peak_allocated_mib', 'peak_reserved_mib'):
                row[key] = {'baseline': a[key], 'candidate': b[key],
                            'delta': b[key] - a[key] if a[key] is not None and b[key] is not None else None}
        report.append(row)
    return dict(baseline_mode=base['mode'], candidate_mode=test['mode'], results=report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.before, args.after), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
