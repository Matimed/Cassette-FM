#!/usr/bin/env bash
# Instala Spotify Soloist como servicio de usuario para las emisoras de Spotify de cassette-fm (idempotente).
# Requisitos: cuenta Premium y la API key de Soloist en ~/.config/cassette-fm/soloist.key (modo 600).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base="${XDG_DATA_HOME:-$HOME/.local/share}/cassette-fm/soloist"
cache="${XDG_CACHE_HOME:-$HOME/.cache}/cassette-fm/soloist"
key="${XDG_CONFIG_HOME:-$HOME/.config}/cassette-fm/soloist.key"
estado="${XDG_STATE_HOME:-$HOME/.local/state}/cassette-fm"
unidad_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [ ! -s "$key" ]; then
    echo "Falta la API key de Soloist en $key." >&2
    echo "Generala en https://developer.spotify.com/dashboard/soloist, guardala en ese archivo y corré:" >&2
    echo "  chmod 600 $key" >&2
    exit 1
fi
chmod 600 "$key"

"$repo/.venv/bin/pip" install -q -e "$repo"       # trae la dependencia websockets
"$repo/scripts/actualizar-soloist.sh" --sin-reiniciar
mkdir -p "$base/datos" "$cache" "$unidad_dir"

if [ ! -e "$base/datos/settings" ]; then
    if [ -e "$repo/spikes/spotify/soloist-data/settings" ]; then
        cp -a "$repo/spikes/spotify/soloist-data/." "$base/datos/"
        echo "Se reusó el emparejamiento de la prueba de Soloist."
    else
        echo "Emparejamiento (una sola vez): abrí Spotify en el celular, en la misma Wi-Fi, tocá el ícono de"
        echo "dispositivos y elegí «cassette-fm»."
        "$base/bin/soloist" -n cassette-fm -k "$(cat "$key")" -D "$base/datos" -C "$cache" --pair
    fi
fi

sed -e "s|@SOLOIST@|$base/bin/soloist|" -e "s|@NOMBRE@|cassette-fm|" -e "s|@KEY@|$key|" \
    -e "s|@DATOS@|$base/datos|" -e "s|@CACHE@|$cache|" \
    "$repo/packaging/cassette-soloist.service.in" > "$unidad_dir/cassette-soloist.service"
systemctl --user daemon-reload
systemctl --user enable --now cassette-soloist

[ -e "$estado/spotify-token.json" ] || "$repo/.venv/bin/cassette" spotify login
echo "Listo. Reiniciá la radio (systemctl --user restart cassette-fm) y mirá: cassette spotify estado"
