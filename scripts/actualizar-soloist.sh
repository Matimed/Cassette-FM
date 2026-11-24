#!/usr/bin/env bash
# Baja el build actual de Spotify Soloist (vencen a los 90 días) y reinicia su servicio. Lo usa también
# scripts/instalar-spotify.sh (con --sin-reiniciar, porque el servicio todavía no existe).
# Uso: scripts/actualizar-soloist.sh [--sin-reiniciar]
set -euo pipefail

[ "$(uname -m)" = "x86_64" ] || { echo "Este script solo baja Soloist para x86_64." >&2; exit 1; }
base="${XDG_DATA_HOME:-$HOME/.local/share}/cassette-fm/soloist"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL -o "$tmp/soloist.tar.gz" https://soloist-builds.spotifycdn.com/soloist_release_x86_64.tar.gz
tar xzf "$tmp/soloist.tar.gz" -C "$tmp"
mkdir -p "$base/bin"
install -m 755 "$tmp/soloist" "$base/bin/soloist"
"$base/bin/soloist" --version
if [ "${1:-}" != "--sin-reiniciar" ]; then
    if systemctl --user cat cassette-soloist >/dev/null 2>&1; then
        systemctl --user restart cassette-soloist
        echo "Soloist actualizado y reiniciado."
    else
        echo "Soloist actualizado. Todavía no tiene servicio: para instalarlo, scripts/instalar-spotify.sh."
    fi
fi
