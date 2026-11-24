#!/usr/bin/env bash
# Instala la integración con Cinnamon: los atajos de teclado y el applet del panel (con el dial). Necesita la radio instalada
# (scripts/instalar-radio.sh). Idempotente: no pisa los atajos que ya uses ni los que hayas cambiado a mano.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo/scripts/lib/comun.sh"

requerir_radio
requerir_comando gsettings "Hace falta para hablar con Cinnamon (viene con el escritorio)."
export PATH="$bin_dir:$PATH"      # `cassette atajos` registra el comando tal como lo encuentra en el PATH

"$repo/.venv/bin/cassette" atajos
"$repo/.venv/bin/cassette" applet

echo
echo "Escritorio instalado. Falta un paso: recargá Cinnamon con Ctrl+Alt+Esc para ver el applet en el panel."
