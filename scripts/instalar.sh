#!/usr/bin/env bash
# Instala cassette-fm como servicio de usuario (idempotente).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="${HOME}/.local/bin"
unidad_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

[ -d "$repo/.venv" ] || python3 -m venv "$repo/.venv"
"$repo/.venv/bin/pip" install -q -e "$repo"

mkdir -p "$bin" "$unidad_dir"
ln -sfn "$repo/.venv/bin/cassette" "$bin/cassette"
sed "s|@CASSETTE@|$repo/.venv/bin/cassette|" "$repo/packaging/cassette-fm.service.in" \
    > "$unidad_dir/cassette-fm.service"

systemctl --user daemon-reload
systemctl --user enable --now cassette-fm
echo "cassette-fm instalado. Probá: cassette list && cassette on"
