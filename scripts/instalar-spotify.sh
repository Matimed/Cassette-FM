#!/usr/bin/env bash
# Instala las emisoras de Spotify de cassette-fm completas: baja Spotify Soloist, lo empareja con tu cuenta, instala su servicio
# de usuario (dirigido al bus de audio de la radio, salvo que tengas bus_audio = false), hace el login en la Web API y reinicia
# la radio para que lo tome. Idempotente.
# Necesita: la radio instalada (scripts/instalar-radio.sh), cuenta Premium y la API key de Soloist en
# ~/.config/cassette-fm/soloist.key (modo 600).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo/scripts/lib/comun.sh"

base="${XDG_DATA_HOME:-$HOME/.local/share}/cassette-fm/soloist"
cache="${XDG_CACHE_HOME:-$HOME/.cache}/cassette-fm/soloist"
key="$config_dir/cassette-fm/soloist.key"
estado="${XDG_STATE_HOME:-$HOME/.local/state}/cassette-fm"

requerir_radio
requerir_comando curl "Instalalo primero (sudo apt install curl)."
if [ ! -s "$key" ]; then
    echo "Falta la API key de Soloist en $key." >&2
    echo "Generala en https://developer.spotify.com/dashboard/soloist, guardala en ese archivo y corré:" >&2
    echo "  chmod 600 $key" >&2
    exit 1
fi
chmod 600 "$key"

# 1. el binario (los builds vencen a los 90 días: para renovarlo después, scripts/actualizar-soloist.sh)
"$repo/scripts/actualizar-soloist.sh" --sin-reiniciar
mkdir -p "$base/datos" "$cache" "$unidad_dir"

# 2. el emparejamiento con tu cuenta (una sola vez)
if [ ! -e "$base/datos/settings" ]; then
    echo "Emparejamiento (una sola vez): abrí Spotify en el celular, en la misma Wi-Fi, tocá el ícono de"
    echo "dispositivos y elegí «cassette-fm»."
    "$base/bin/soloist" -n cassette-fm -k "$(cat "$key")" -D "$base/datos" -C "$cache" --pair
fi

# 3. el servicio, y el audio de Soloist dirigido al bus de la radio
sed -e "s|@SOLOIST@|$base/bin/soloist|" -e "s|@NOMBRE@|cassette-fm|" -e "s|@KEY@|$key|" \
    -e "s|@DATOS@|$base/datos|" -e "s|@CACHE@|$cache|" \
    "$repo/packaging/cassette-soloist.service.in" > "$unidad_dir/cassette-soloist.service"
if bus_audio_activo; then
    enrutar_soloist_al_bus
else
    soltar_soloist_del_bus
    echo "Aviso: tenés bus_audio = false, así que Soloist suena directo por tu salida de audio (sin el volumen de la radio)."
fi
systemctl --user daemon-reload
systemctl --user enable cassette-soloist

# 4. el permiso de la Web API (se abre el navegador; una sola vez)
[ -e "$estado/spotify-token.json" ] || "$repo/.venv/bin/cassette" spotify login

# 5. la radio y Soloist arrancan juntos (la radio crea el bus antes que Soloist; la música se corta un instante)
systemctl --user restart cassette-fm cassette-soloist
esperar_hasta 20 "$repo/.venv/bin/cassette" status ||
    fallar "La radio no responde. Mirá: journalctl --user -u cassette-fm -n 20"

echo "Spotify instalado. Mirá: cassette spotify estado"
echo "Crear una emisora: cassette nueva \"Nombre\" <link de tu playlist>"
