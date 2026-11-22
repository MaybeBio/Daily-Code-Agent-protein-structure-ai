#!/usr/bin/env python3
"""Plot transport CSV and fitted results using a noninteractive backend."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def plot(out):
    data = np.genfromtxt(out / 'transport_curves.csv', delimiter=',', names=True)
    result = json.loads((out / 'transport.json').read_text())
    time = data['lag_ps']
    panels = [
        ('self_msd', [('li_self_msd_A2', 'Cation'), ('tfsi_self_msd_A2', 'Anion')], 'Self MSD (Å²)'),
        ('collective_displacements', [('li_collective_A2', 'Cation'), ('tfsi_collective_A2', 'Anion'), ('li_tfsi_cross_A2', 'Cation–anion cross')], 'Collective displacement (Å²)'),
        ('charge_displacement', [('charge_collective_A2', 'Charge collective')], 'Charge displacement (Å²)'),
    ]
    for name, curves, ylabel in panels:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for column, label in curves:
            ax.plot(time, data[column], label=label)
            if 'fit_ps' in result:
                start, end = result['fit_ps']
                mask = (time >= start) & (time <= end)
                coefficients = np.polyfit(time[mask], data[column][mask], 1)
                ax.plot(time[mask], np.polyval(coefficients, time[mask]), '--', color='black', alpha=.6)
        if 'fit_ps' in result:
            ax.axvspan(*result['fit_ps'], color='orange', alpha=.12, label='Fit window')
        ax.set(xlabel='Lag time (ps)', ylabel=ylabel)
        ax.legend()
        ax.grid(alpha=.2)
        fig.tight_layout()
        for extension in ('png', 'pdf'):
            fig.savefig(out / f'{name}.{extension}', dpi=300)
        plt.close(fig)
    print(f'Plots saved in {out}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='Analysis directory')
    plot(parser.parse_args().out)
