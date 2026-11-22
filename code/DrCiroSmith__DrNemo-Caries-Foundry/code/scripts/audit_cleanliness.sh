#!/usr/bin/env bash
# audit_cleanliness.sh - Precise forbidden-token scan (no false positives)
cd "$(dirname "$0")/.."

echo "=== AUDIT: SCANNING CODE & METRICS (EXCLUDING ATOM COORDINATE FILES) ==="

HITS=""

# Pattern 1: fake pLDDT / iPTM values (require neighboring context, not bare 0.89)
HIT1=$(grep -rnE 'pLDDT\s+94\.20|iPTM\s+0\.88|94\.20.*pLDDT|0\.88.*iPTM' . \
  --exclude-dir='.git' --exclude-dir='.venv' --exclude-dir='data/poses' \
  --exclude='*.pdb' --exclude='*.pdbqt' --exclude='*.pyc' \
  --exclude='audit_cleanliness.sh' || true)
[ -n "$HIT1" ] && HITS="$HITS
$HIT1"

# Pattern 2: known synthetic mock score sentinels
HIT2=$(grep -rnE '\-14\.02|144\.1|abcdef654321' . \
  --exclude-dir='.git' --exclude-dir='.venv' --exclude-dir='data/poses' \
  --exclude='*.pdb' --exclude='*.pdbqt' --exclude='*.pyc' \
  --exclude='audit_cleanliness.sh' || true)
[ -n "$HIT2" ] && HITS="$HITS
$HIT2"

# Pattern 3: wrong affiliation email
HIT3=$(grep -rnE 'roi@research-mail\.com' . \
  --exclude-dir='.git' --exclude-dir='.venv' --exclude-dir='data/poses' \
  --exclude='*.pdb' --exclude='*.pdbqt' --exclude='*.pyc' \
  --exclude='audit_cleanliness.sh' || true)
[ -n "$HIT3" ] && HITS="$HITS
$HIT3"

# Pattern 4: numpy random in scripts/notebooks only (CLAUDE.md documents the prohibition - exclude it)
HIT4=$(grep -rnE 'np\.random' . \
  --exclude-dir='.git' --exclude-dir='.venv' --exclude-dir='data/poses' \
  --exclude='*.pdb' --exclude='*.pdbqt' --exclude='*.pyc' \
  --exclude='audit_cleanliness.sh' --exclude='CLAUDE.md' || true)
[ -n "$HIT4" ] && HITS="$HITS
$HIT4"

if [ -n "$HITS" ]; then
    echo "FOUND FORBIDDEN TOKENS:"
    echo "$HITS"
    exit 1
else
    echo "100% CLEAN: ZERO FORBIDDEN TOKENS IN ANY SOURCE, MD, JSON, OR SCRIPT!"
    exit 0
fi
