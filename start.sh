#!/bin/sh
# Bootstraps a persistent venv in /data (appdata) so restarts are offline-safe.
set -e

VENV=/data/venv

[ -d "$VENV" ] || python -m venv "$VENV"

# Only hit the network if the dep is actually missing.
"$VENV/bin/python" -c 'import discord' 2>/dev/null \
  || "$VENV/bin/pip" install --quiet --no-cache-dir "discord.py>=2.4"

exec "$VENV/bin/python" -u /app/bot.py
