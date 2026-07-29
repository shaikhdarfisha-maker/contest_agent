#!/usr/bin/env bash
# One-shot setup for a fresh Mac. Run this from inside the cloned contest_agent folder,
# AFTER you've AirDropped over secrets_bundle.zip (made by ./bundle_secrets.sh on the old Mac)
# and placed it in this same folder.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== NV Contest Agent — New Machine Setup ==="
echo ""

echo "--- Step 1/5: Homebrew tools (python@3.11, ngrok) ---"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew isn't installed. Install it first from https://brew.sh, then re-run this script."
  exit 1
fi
brew install python@3.11 ngrok

echo ""
echo "--- Step 2/5: Python packages ---"
python3.11 -m pip install -r requirements.txt

echo ""
echo "--- Step 3/5: Browser for the automation (Playwright Chromium) ---"
python3.11 -m playwright install chromium

echo ""
echo "--- Step 4/5: Private/secret files ---"
if [ -f "secrets_bundle.zip" ]; then
  unzip -o secrets_bundle.zip
  rm secrets_bundle.zip
  echo "Secret files unpacked into place."
else
  echo "WARNING: secrets_bundle.zip not found in this folder."
  echo "Go back to the old Mac, run ./bundle_secrets.sh there, AirDrop the resulting"
  echo "secrets_bundle.zip into this folder, then re-run this script."
  exit 1
fi

echo ""
echo "--- Step 5/5: ngrok account key ---"
echo "Get your key from https://dashboard.ngrok.com (Your Authtoken page), then paste it below."
read -rp "Paste your ngrok authtoken: " NGROK_TOKEN
ngrok config add-authtoken "$NGROK_TOKEN"

echo ""
echo "=== Setup complete ==="
echo "Two things left, both need you to do them by hand:"
echo "  1. python3.11 capture_login.py   (log in to Scaler in the browser that opens)"
echo "  2. ./start.sh                    (starts the app)"
