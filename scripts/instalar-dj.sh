#!/usr/bin/env bash
# Instala el servicio DJ de cassette-fm completo: el extra [dj,piper], el comando `cassette-dj`, los modelos de voz de Kokoro
# (~350 MB, una sola vez) y el servicio de usuario `cassette-dj`. Idempotente.
# No necesita la radio: el servicio DJ puede vivir en otra máquina (en ese caso, copiá el proyecto allá y corré esto). Para que
# una radio lo use falta apuntarla en su config.toml: [dj] activo = true y url = "http://<esta máquina>:7720".
#
#   scripts/instalar-dj.sh [--voz-piper MODELO]...
#
# --voz-piper baja además un modelo de voz de Piper (se puede repetir), por ejemplo es_AR-daniela-high (español rioplatense).
# Las voces disponibles: https://huggingface.co/rhasspy/piper-voices
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo/scripts/lib/comun.sh"

modelos_dir="${XDG_DATA_HOME:-$HOME/.local/share}/cassette-dj/modelos"
voces_piper=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --voz-piper)
            [ "$#" -ge 2 ] || fallar "--voz-piper pide el nombre de un modelo (por ejemplo es_AR-daniela-high)."
            voces_piper+=("$2")
            shift 2
            ;;
        *) fallar "Uso: scripts/instalar-dj.sh [--voz-piper MODELO]..." ;;
    esac
done

requerir_python
requerir_systemd_usuario

preparar_venv "[dj,piper]"
enlazar_comando cassette-dj

# los modelos van antes de arrancar el servicio: sin ellos no puede hablar
"$repo/.venv/bin/cassette-dj" modelos
for voz in ${voces_piper[@]+"${voces_piper[@]}"}; do
    "$repo/.venv/bin/python" -m piper.download_voices --download-dir "$modelos_dir/piper" "$voz"
done

mkdir -p "$unidad_dir"
sed "s|@CASSETTE_DJ@|$repo/.venv/bin/cassette-dj|" "$repo/packaging/cassette-dj.service.in" > "$unidad_dir/cassette-dj.service"

systemctl --user daemon-reload
systemctl --user enable cassette-dj
# restart y no `enable --now`: un servicio ya levantado sigue con el código viejo hasta reiniciarlo
systemctl --user restart cassette-dj

if command -v curl >/dev/null 2>&1; then
    esperar_hasta 30 curl -fsS "http://127.0.0.1:7720/salud" ||
        echo "Aviso: el servicio DJ no respondió en 127.0.0.1:7720 (si cambiaste el puerto, es normal). Mirá: journalctl --user -u cassette-dj -n 20" >&2
fi

echo "Servicio DJ instalado."
echo "Para escuchar al DJ en la radio: poné [dj] activo = true y url = \"http://127.0.0.1:7720\" en $config_dir/cassette-fm/config.toml (ver docs/setup.md)."
avisar_si_falta_en_el_path
