# Funciones compartidas por los instaladores de scripts/. No se ejecuta: se carga con `source`.
# Quien la cargue define antes `repo` (la raíz del proyecto) y activa `set -euo pipefail`.

bin_dir="$HOME/.local/bin"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}"
unidad_dir="$config_dir/systemd/user"
config_radio="$config_dir/cassette-fm/config.toml"
dropin_bus_dir="$unidad_dir/cassette-soloist.service.d"
dropin_bus="$dropin_bus_dir/bus-audio.conf"

fallar() {
    echo "$*" >&2
    exit 1
}

# requerir_comando COMANDO "qué hacer si falta"
requerir_comando() {
    command -v "$1" >/dev/null 2>&1 || fallar "No encuentro $1. $2"
}

requerir_python() {
    requerir_comando python3 "Instalalo primero (hace falta Python 3.12 o más nuevo)."
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' ||
        fallar "Hace falta Python 3.12 o más nuevo (este es $(python3 --version 2>&1))."
}

requerir_systemd_usuario() {
    requerir_comando systemctl "Hace falta systemd."
    systemctl --user show-environment >/dev/null 2>&1 ||
        fallar "systemd no responde en modo usuario: corré el script desde tu sesión de escritorio (no por su ni sudo)."
}

# La radio instalada: el comando en el entorno del proyecto y su unidad. La piden los componentes que se le enchufan.
requerir_radio() {
    { [ -x "$repo/.venv/bin/cassette" ] && [ -e "$unidad_dir/cassette-fm.service" ]; } ||
        fallar "Falta la radio: corré primero scripts/instalar-radio.sh."
}

# preparar_venv [EXTRAS]   (por ejemplo "[dj,piper]"): el entorno virtual del proyecto con el paquete instalado en modo editable.
preparar_venv() {
    [ -d "$repo/.venv" ] || python3 -m venv "$repo/.venv"
    "$repo/.venv/bin/pip" install -q -e "$repo${1:-}"
}

# enlazar_comando NOMBRE: deja el comando del entorno del proyecto en ~/.local/bin.
enlazar_comando() {
    mkdir -p "$bin_dir"
    ln -sfn "$repo/.venv/bin/$1" "$bin_dir/$1"
}

avisar_si_falta_en_el_path() {
    case ":$PATH:" in
        *":$bin_dir:"*) ;;
        *) echo "Ojo: $bin_dir no está en tu PATH, y ahí vive el comando. En bash cerrá y abrí la sesión; en fish: fish_add_path $bin_dir" ;;
    esac
}

unidad_instalada() {
    [ -e "$unidad_dir/$1.service" ]
}

# esperar_hasta SEGUNDOS COMANDO...: reintenta cada segundo hasta que el comando anda.
esperar_hasta() {
    local segundos="$1"
    shift
    local _
    for _ in $(seq 1 "$segundos"); do
        "$@" >/dev/null 2>&1 && return 0
        sleep 1
    done
    return 1
}

# --- Bus de audio: la clave de la radio y el enrutado de Soloist ---

bus_audio_activo() {
    ! grep -Eq '^[[:space:]]*bus_audio[[:space:]]*=[[:space:]]*false' "$config_radio" 2>/dev/null
}

# las claves sueltas del TOML van antes de la primera tabla [..]
poner_bus_audio() {
    mkdir -p "$(dirname "$config_radio")"
    touch "$config_radio"
    sed -i '/^bus_audio = /d' "$config_radio"
    { echo "bus_audio = $1"; cat "$config_radio"; } > "$config_radio.tmp" && mv "$config_radio.tmp" "$config_radio"
}

# Soloist es un cliente PipeWire nativo (ignora PULSE_SINK): se dirige al bus con PIPEWIRE_NODE, desde un drop-in de su unidad.
# PartOf/After: arranca con el bus ya creado y se reinicia con cassette-fm (que descarga el bus al salir).
enrutar_soloist_al_bus() {
    mkdir -p "$dropin_bus_dir"
    cat > "$dropin_bus" <<UNIT
[Unit]
PartOf=cassette-fm.service
After=cassette-fm.service

[Service]
Environment=PIPEWIRE_NODE=radio_virtual
UNIT
}

soltar_soloist_del_bus() {
    rm -f "$dropin_bus"
    rmdir "$dropin_bus_dir" 2>/dev/null || true
}
