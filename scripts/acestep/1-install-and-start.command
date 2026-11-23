#!/bin/bash
# FretCase: installs ACE-Step 1.5 on this Mac and starts its API server (http://127.0.0.1:8001).
# Double-click this file in Finder, or run:  bash 1-install-and-start.command
# Leave the window open while you try things; close it (or press Ctrl-C) to stop the server.
set -e
DIR="$HOME/ACE-Step-1.5"

if [ "$(uname -m)" != "arm64" ]; then echo "This script is for Apple Silicon Macs."; exit 1; fi
if ! command -v git >/dev/null; then echo "git is missing. Run 'xcode-select --install' first, then run this again."; exit 1; fi

if [ ! -d "$DIR/.git" ]; then
  echo "This will download ACE-Step 1.5 (open source, MIT licence) into:"
  echo "    $DIR"
  echo "The code and its Python packages take a few GB; the models (about 10 GB more)"
  echo "download the first time the server starts. Free disk space needed: about 20 GB."
  echo
  read -rp "Press Enter to continue, or Ctrl-C to stop. " _
  git clone --depth 1 https://github.com/ace-step/ACE-Step-1.5.git "$DIR"
fi
cd "$DIR"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null; then
  echo
  echo "ACE-Step needs the 'uv' Python package manager (https://astral.sh/uv)."
  read -rp "Press Enter to install it for your user account, or Ctrl-C to stop. " _
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

echo
echo "Setting up the Python environment (a few minutes the first time)..."
uv sync

export ACESTEP_LM_BACKEND=mlx       # Apple Silicon backend for the language model
export TOKENIZERS_PARALLELISM=false
echo
echo "Starting the ACE-Step API server on http://127.0.0.1:8001"
echo "The first start downloads the models; wait for the line that says the server is running,"
echo "then double-click 2-try-cover.command."
echo
exec uv run acestep-api --host 127.0.0.1 --port 8001
