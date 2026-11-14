#!/usr/bin/env bash
# Instala el servidor de LLM del DJ de cassette-fm: Ollama dentro de Docker (idempotente) y baja el modelo.
# Uso: scripts/instalar-llm.sh [modelo]     (por defecto, el `llm_modelo` de la configuración del servicio DJ)
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
contenedor="cassette-ollama"
datos="${XDG_DATA_HOME:-$HOME/.local/share}/cassette-dj/ollama"

if ! command -v docker >/dev/null 2>&1; then
    echo "No encuentro docker. Instalalo primero (por ejemplo: sudo apt install docker.io)." >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "Docker no responde con tu usuario. Si recién lo instalaste: sudo usermod -aG docker \"\$USER\" y volvé a iniciar sesión." >&2
    exit 1
fi

if [ "$#" -ge 1 ]; then
    modelo="$1"
else
    modelo="$("$repo/.venv/bin/cassette-dj" llm modelo 2>/dev/null || echo "gemma3:4b")"
fi

mkdir -p "$datos"
if docker ps -a --format '{{.Names}}' | grep -qx "$contenedor"; then
    docker start "$contenedor" >/dev/null
    echo "El contenedor $contenedor ya existía: se reutiliza."
else
    docker run -d --name "$contenedor" --restart unless-stopped -p 127.0.0.1:11434:11434 \
        -v "$datos:/root/.ollama" ollama/ollama >/dev/null
    echo "Contenedor $contenedor creado (solo escucha en 127.0.0.1:11434)."
fi

for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
curl -fsS "http://127.0.0.1:11434/api/tags" >/dev/null || { echo "Ollama no arrancó: mirá docker logs $contenedor" >&2; exit 1; }

echo "Bajando el modelo $modelo (puede tardar y ocupa unos GB) ..."
docker exec "$contenedor" ollama pull "$modelo"

echo "Listo. Probalo con:  cassette-dj llm estado   y   cassette dj modo llm"
echo "Para borrar todo:    docker rm -f cassette-ollama   y borrar la carpeta $datos"
