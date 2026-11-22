#!/usr/bin/env bash
# Blind docking with an independent scoring function (Vinardo) in AutoDock Vina 1.2.5; same box and settings as the primary run.
vina --receptor receptor.pdbqt --ligand PRIMA1.pdbqt --scoring vinardo \
  --center_x 2.869 --center_y -0.294 --center_z 31.059 \
  --size_x 57.649 --size_y 49.494 --size_z 57.319 \
  --exhaustiveness 32 --num_modes 20 --out docking_vinardo.pdbqt > vina_vinardo_log.txt
