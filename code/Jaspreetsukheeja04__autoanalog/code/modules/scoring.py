# modules/scoring.py
# This file calculates the final composite
# score that ranks all drug candidates.
# Used by: scripts/09_ranking.py

def composite_score(row):
    # Takes one row from the results table
    # and calculates a single overall score.
    # Higher score = better candidate.

    # ML model prediction (0 to 1)
    ml = row.get('ml_score', 0)

    # Docking score normalized (0 to 1)
    # Already normalized before calling this
    dock = row.get('dock_norm', 0)

    # Lipinski pass = 1, fail = 0
    lip = 1 if row.get('Lipinski') == 'PASS' else 0

    # QED drug-likeness score (0 to 1)
    qed = row.get('QED', 0)

    # CNS ready = 1 means can reach the brain
    cns = 1 if row.get('CNS_ready') == 'YES' else 0

    # Bleeding risk flag
    bleed = 1 if row.get('Bleeding_risk') == 'HIGH' else 0

    # Weighted combination
    # Docking gets highest weight because it is
    # most direct evidence of binding to P2Y12
    score = (0.25 * ml   +
             0.30 * dock +
             0.15 * lip  +
             0.15 * qed  +
             0.15 * cns)

    # Penalty for high bleeding risk
    # This is critical for P2Y12 specifically
    score -= 0.20 * bleed

    return round(score, 3)

def normalize_docking(df):
    # Converts docking scores from kcal/mol
    # into a 0 to 1 scale where 1 is best.
    # More negative docking score is better
    # so we flip the scale.
    dmin = df['docking_score'].min()
    dmax = df['docking_score'].max()
    df['dock_norm'] = (dmin - df['docking_score']) / \
                      (dmin - dmax + 1e-9)
    return df
