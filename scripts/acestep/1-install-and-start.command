#!/bin/bash
# FretCase: installs ACE-Step 1.5 on this Mac and starts its API server (http://127.0.0.1:8001).
# Double-click this file in Finder, or run:  bash 1-install-and-start.command
# Leave the window open while you try things; close it (or press Ctrl-C) to stop the server.
set -e
DIR="$HOME/ACE-Step-1.5"

# Keep the Mac awake while this window is open (a sleeping Mac stops the download and the server).
caffeinate -dims -w $$ &

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

# The models: fetched here, in the open, so a failed download shows its reason (the server's own
# on-demand download fails quietly and then reports "checkpoint not found").
has_weights() { [ -n "$(find "checkpoints/$1" -type f \( -name '*.safetensors' -o -name '*.bin' -o -name '*.pt' -o -name '*.pth' -o -name '*.ckpt' \) -size +1M 2>/dev/null | head -1)" ]; }
if ! has_weights acestep-v15-turbo || ! has_weights vae || ! has_weights Qwen3-Embedding-0.6B; then
  echo
  echo "Downloading the ACE-Step models into $DIR/checkpoints (about 10 GB, shown with progress)..."
  # The models are public. A saved Hugging Face login that has expired makes Hugging Face answer
  # 401 for them, so download without sending any saved token.
  unset HF_TOKEN HUGGING_FACE_HUB_TOKEN
  export HF_HUB_DISABLE_IMPLICIT_TOKEN=1
  uv run acestep-download || true
  if ! has_weights acestep-v15-turbo; then
    echo
    echo "Hugging Face did not deliver the models; trying ModelScope instead..."
    ACESTEP_DOWNLOAD_SOURCE=modelscope uv run acestep-download || true
  fi
fi
if ! has_weights acestep-v15-turbo; then
  echo
  echo "The download ended but $DIR/checkpoints/acestep-v15-turbo has no model files."
  echo "Copy everything in this window and send it to Claude."
  ls -la checkpoints 2>/dev/null
  read -rp "Press Enter to close. " _
  exit 1
fi

unset HF_TOKEN HUGGING_FACE_HUB_TOKEN
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1
export ACESTEP_LM_BACKEND=mlx       # Apple Silicon backend for the language model
export TOKENIZERS_PARALLELISM=false
echo
echo "Starting the ACE-Step API server on http://127.0.0.1:8001"
echo "Wait for the line \"Uvicorn running on http://127.0.0.1:8001\", then double-click 2-try-cover.command."
echo "(The first song takes longer: the models are loaded into memory then.)"
echo
exec uv run acestep-api --host 127.0.0.1 --port 8001
