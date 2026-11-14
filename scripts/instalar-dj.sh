#!/usr/bin/env bash
# Instala el servicio DJ de cassette-fm como servicio de usuario (idempotente).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="${HOME}/.local/bin"
unidad_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

[ -d "$repo/.venv" ] || python3 -m venv "$repo/.venv"
"$repo/.venv/bin/pip" install -q -e "$repo[dj,piper]"

mkdir -p "$bin" "$unidad_dir"
ln -sfn "$repo/.venv/bin/cassette-dj" "$bin/cassette-dj"
sed "s|@CASSETTE_DJ@|$repo/.venv/bin/cassette-dj|" "$repo/packaging/cassette-dj.service.in" \
    > "$unidad_dir/cassette-dj.service"

systemctl --user daemon-reload
systemctl --user enable --now cassette-dj
echo "cassette-dj instalado."
echo "Falta bajar los modelos de voz (unos 350 MB, una sola vez):  cassette-dj modelos"
