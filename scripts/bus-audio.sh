#!/usr/bin/env bash
# Prende o apaga el bus de audio virtual de la radio (`bus_audio` en config.toml), con todo lo que cuelga de él: si Soloist está
# instalado, también le pone o le saca el enrutado al bus, y reinicia lo que haga falta. Idempotente.
#
#   scripts/bus-audio.sh activar      (es el valor de fábrica: solo hace falta si lo habías quitado)
#   scripts/bus-audio.sh quitar       la radio sin bus: se pierden el volumen unificado, la retransmisión por red y el sueño automático
#
# Necesita la radio instalada (scripts/instalar-radio.sh). Para instalar Spotify no hace falta correrlo: lo resuelve
# scripts/instalar-spotify.sh.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo/scripts/lib/comun.sh"

accion="${1:-activar}"
case "$accion" in
    activar|quitar) ;;
    *) fallar "Uso: scripts/bus-audio.sh [activar|quitar]" ;;
esac

requerir_radio
requerir_systemd_usuario

if [ "$accion" = "quitar" ]; then
    poner_bus_audio false
    soltar_soloist_del_bus
else
    requerir_comando pactl "Instalalo primero (sudo apt install pulseaudio-utils): el bus se maneja con pactl."
    poner_bus_audio true
    if unidad_instalada cassette-soloist; then
        enrutar_soloist_al_bus
    fi
fi

systemctl --user daemon-reload
if unidad_instalada cassette-soloist; then
    systemctl --user restart cassette-fm cassette-soloist
else
    systemctl --user restart cassette-fm
fi
esperar_hasta 20 "$repo/.venv/bin/cassette" status ||
    fallar "La radio no responde. Mirá: journalctl --user -u cassette-fm -n 20"

if [ "$accion" = "activar" ]; then
    echo "Bus de audio activado. Mirá: pactl list short sinks | grep radio_virtual"
else
    echo "Bus de audio desactivado: la radio suena directo por tu salida de audio."
fi
