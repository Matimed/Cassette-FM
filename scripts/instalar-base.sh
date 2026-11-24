#!/usr/bin/env bash
# Instala lo básico para usar cassette-fm en el escritorio: la radio y la integración con Cinnamon. No agrega nada propio:
# corre, en orden, scripts/instalar-radio.sh y scripts/instalar-escritorio.sh (cada uno se puede usar por su cuenta).
# Spotify, el DJ y el LLM son componentes aparte: scripts/instalar-spotify.sh, instalar-dj.sh e instalar-llm.sh.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$repo/scripts/instalar-radio.sh"
"$repo/scripts/instalar-escritorio.sh"
