#!/usr/bin/env bash
# Instala todo cassette-fm en el escritorio con un solo comando (idempotente):
# servicio, comando `cassette`, atajos de teclado y applet del panel.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

"$repo/scripts/instalar.sh"
# el servicio ya levantado sigue con el código viejo hasta reiniciarlo (corta la música un instante)
systemctl --user restart cassette-fm
"$repo/.venv/bin/cassette" atajos
"$repo/.venv/bin/cassette" applet

echo
echo "Listo. Falta un paso: recargá Cinnamon con Ctrl+Alt+Esc para ver el applet en el panel."
