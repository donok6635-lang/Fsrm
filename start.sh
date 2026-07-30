#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Install Python dependencies if needed
if ! python3 -c "import discord" 2>/dev/null; then
  echo "📦 Installing Python dependencies..."
  pip install -r requirements.txt --quiet
fi

echo "🤖 Starting FarmBot..."
exec python3 bot.py
