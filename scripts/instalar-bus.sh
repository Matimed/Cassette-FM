#!/bin/sh
# Prepara el bus de audio virtual (radio_virtual), que cassette-fm crea por defecto (`bus_audio = true`).
# Soloist es un cliente PipeWire nativo (ignora PULSE_SINK): se dirige al bus con PIPEWIRE_NODE, desde un drop-in de
# su unidad. Idempotente. Para volver a la radio sin bus: scripts/instalar-bus.sh quitar
set -eu
config="${XDG_CONFIG_HOME:-$HOME/.config}/cassette-fm/config.toml"
drop_in_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/cassette-soloist.service.d"
drop_in="$drop_in_dir/bus-audio.conf"

# las claves sueltas del TOML van antes de la primera tabla [..]
poner_bus_audio() {
    mkdir -p "$(dirname "$config")"
    touch "$config"
    sed -i '/^bus_audio = /d' "$config"
    { echo "bus_audio = $1"; cat "$config"; } > "$config.tmp" && mv "$config.tmp" "$config"
}

if [ "${1:-}" = "quitar" ]; then
    rm -f "$drop_in"
    rmdir "$drop_in_dir" 2>/dev/null || true
    poner_bus_audio false
else
    mkdir -p "$drop_in_dir"
    # PartOf/After: Soloist arranca con el bus ya creado y se reinicia con cassette-fm (que descarga el bus al salir)
    cat > "$drop_in" <<UNIT
[Unit]
PartOf=cassette-fm.service
After=cassette-fm.service

[Service]
Environment=PIPEWIRE_NODE=radio_virtual
UNIT
    poner_bus_audio true
fi
systemctl --user daemon-reload
systemctl --user restart cassette-fm cassette-soloist
echo "Listo. Mirá: pactl list short sinks | grep radio_virtual"
