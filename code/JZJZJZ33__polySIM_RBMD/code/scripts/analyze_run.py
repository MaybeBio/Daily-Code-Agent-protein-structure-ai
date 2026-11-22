#!/usr/bin/env python3
"""Generate polymer-electrolyte properties, transport properties and PNG/PDF plots."""
import argparse
from pathlib import Path
from generate_species_map import generate
from analyze_transport import analyze
from plot_transport import plot

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run', required=True, type=Path)
parser.add_argument('--trajectory', type=Path, help='Defaults to complete trajectory if available')
parser.add_argument('--species', type=Path, help='Existing map, retained without regeneration')
parser.add_argument('--definitions', type=Path, help='Species definitions for a new map')
parser.add_argument('--fit-ps', nargs=2, type=float, required=True)
args = parser.parse_args()
stage = args.run / '03-production'
trajectory = args.trajectory
if trajectory is None:
    trajectory = stage / 'rbmd_complete.trj'
    if not trajectory.exists():
        trajectory = stage / 'rbmd.trj'
out = args.run / 'analysis'
out.mkdir(parents=True, exist_ok=True)
species = args.species or args.run / 'species_map.json'
if not species.exists():
    import json
    if args.definitions is None:
        parser.error('Supply --species or --definitions; use generate_species_map.py for the bundled example')
    generate(args.run / 'packed.data', species, json.loads(args.definitions.read_text()))
analyze(trajectory, args.run / 'packed.data', species, stage / 'rbmd.json', out, args.fit_ps)
plot(out)
print((out / 'transport.json').read_text())
