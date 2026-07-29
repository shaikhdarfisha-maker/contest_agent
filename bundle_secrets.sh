#!/usr/bin/env bash
# Run this on a Mac that already has a working setup, BEFORE moving to a new machine.
# Zips the 4 private files (never committed to git) into one file so it can be
# AirDropped as a single visible item instead of hunting for hidden dotfiles.
set -euo pipefail
cd "$(dirname "$0")"

FILES=(
  ".env"
  ".streamlit/secrets.toml"
  "data/storage_state.json"
  "data/service_account.json"
)

MISSING=()
PRESENT=()
for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then
    PRESENT+=("$f")
  else
    MISSING+=("$f")
  fi
done

if [ ${#PRESENT[@]} -eq 0 ]; then
  echo "No secret files found here — nothing to bundle. Are you in the contest_agent folder?"
  exit 1
fi

rm -f secrets_bundle.zip
zip secrets_bundle.zip "${PRESENT[@]}"

echo ""
echo "Done. Created: secrets_bundle.zip"
echo "AirDrop just this ONE file to the new Mac, then on that Mac run:"
echo "  ./setup_new_machine.sh"
echo ""
if [ ${#MISSING[@]} -gt 0 ]; then
  echo "Note: these files were not found and were skipped:"
  for f in "${MISSING[@]}"; do
    echo "  - $f"
  done
fi
