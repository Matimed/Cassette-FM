#!/usr/bin/env bash
# Instala la radio de cassette-fm: el entorno virtual del proyecto, el comando `cassette` en ~/.local/bin y el servicio de
# usuario `cassette-fm` (arranca con la sesión). Es el núcleo y no necesita ningún otro componente.
# Idempotente: volver a correrlo actualiza el código y reinicia el servicio (la música se corta un instante).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo/scripts/lib/comun.sh"

requerir_python
requerir_comando mpv "Instalalo primero (sudo apt install mpv)."
requerir_systemd_usuario
command -v pactl >/dev/null 2>&1 || echo "Aviso: no encuentro pactl (sudo apt install pulseaudio-utils). Sin él la radio arranca sin el bus de audio:" \
    "poné bus_audio = false en $config_radio." >&2

preparar_venv
enlazar_comando cassette

mkdir -p "$unidad_dir"
sed "s|@CASSETTE@|$repo/.venv/bin/cassette|" "$repo/packaging/cassette-fm.service.in" > "$unidad_dir/cassette-fm.service"

systemctl --user daemon-reload
systemctl --user enable cassette-fm
# restart y no `enable --now`: un servicio ya levantado sigue con el código viejo hasta reiniciarlo
systemctl --user restart cassette-fm

esperar_hasta 20 "$repo/.venv/bin/cassette" status ||
    fallar "El servicio no responde. Mirá: journalctl --user -u cassette-fm -n 20"

echo "Radio instalada y andando. Probá: cassette list && cassette on"
avisar_si_falta_en_el_path
