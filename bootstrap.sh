#!/usr/bin/env bash
# NV Contest Agent — full setup for a brand new Mac, in one command.
#
# Before running this, get secrets_bundle.zip (made by ./bundle_secrets.sh on
# an already-working Mac) AirDropped into this Mac's Downloads folder.
#
# Then, on the new Mac, open Terminal and paste:
#   curl -fsSL https://raw.githubusercontent.com/shaikhdarfisha-maker/contest_agent/main/bootstrap.sh | bash
set -euo pipefail

REPO_URL="https://github.com/shaikhdarfisha-maker/contest_agent.git"
# NOT ~/Downloads: macOS blocks background/launchd-launched processes from
# accessing Desktop/Documents/Downloads without an explicit permission grant
# that's awkward to give to a raw script. Auto-start on login silently fails
# with "Operation not permitted" if the project lives in Downloads — learned
# the hard way, see CLAUDE.md.
DEST="$HOME/contest_agent"
SECRETS_ZIP="$HOME/Downloads/secrets_bundle.zip"  # AirDrop always lands here; fine to leave

echo "=== NV Contest Agent — Setup ==="
echo ""

echo "--- Step 1/6: Homebrew (the tool installer) ---"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew isn't installed — installing it now."
  echo "(macOS may ask for your Mac password — that's normal, type it and press Enter.)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
fi

echo ""
echo "--- Step 2/6: Installing python, ngrok, git ---"
brew install python@3.11 ngrok git

echo ""
echo "--- Step 3/6: Downloading the project ---"
if [ -d "$DEST/.git" ]; then
  echo "Already downloaded — grabbing the latest version."
  git -C "$DEST" pull
else
  git clone "$REPO_URL" "$DEST"
fi
cd "$DEST"

echo ""
echo "--- Step 4/6: Installing required packages ---"
python3.11 -m pip install -r requirements.txt
python3.11 -m playwright install chromium

echo ""
echo "--- Step 5/6: Private/secret files ---"
if [ -f "$SECRETS_ZIP" ]; then
  unzip -o "$SECRETS_ZIP" -d "$DEST"
  rm "$SECRETS_ZIP"
  echo "Secret files unpacked."
else
  echo "!!! secrets_bundle.zip was not found in your Downloads folder !!!"
  echo ""
  echo "Ask whoever already has this working to open the project on their Mac"
  echo "and run:   ./bundle_secrets.sh"
  echo "Then AirDrop you the one file it creates (secrets_bundle.zip)."
  echo "Save it into YOUR Downloads folder, then run this setup command again."
  exit 1
fi

echo ""
echo "--- Step 6/6: ngrok account key ---"
echo "Go to https://dashboard.ngrok.com in your browser, log in (or sign up — it's free),"
echo "find the page called 'Your Authtoken', and copy the long key shown there."
read -rp "Paste it here and press Enter: " NGROK_TOKEN
ngrok config add-authtoken "$NGROK_TOKEN"

echo ""
echo "=== Setup finished! Two last things, done by hand: ==="
echo ""
echo "1) Run this and log in to Scaler in the browser window that opens:"
echo "     cd ~/contest_agent && python3.11 capture_login.py"
echo ""
echo "2) Then start the app:"
echo "     ./start.sh"
