#!/usr/bin/env bash
# Uso: ./estacion.sh <nombre> <carpeta dentro de ~/Música> <puerto-ui> <puerto-stream> <es|en> <voz-edge>
# Ej:  ./estacion.sh lentos "Lentos" 7710 7702 en en-US-AndrewNeural
set -euo pipefail
NAME=$1 DIR=$2 UI=$3 ST=$4 LANG_=$5 VOICE=$6
docker rm -f "rdj-$NAME" >/dev/null 2>&1 || true
CFG=$(python3 -c 'import json,sys; print(json.dumps({
 "library": "/music/"+sys.argv[1], "source": "folder", "station_name": sys.argv[2],
 "llm_provider": "ollama", "glm_base_url": "http://rdj-ollama:11434/v1", "glm_model": "qwen2.5:3b", "glm_api_key": "ollama",
 "voice_cmd": "tts-retry "+sys.argv[4]+" {text} {out}", "language": sys.argv[3],
 "location": "Buenos Aires", "lat": -34.6037, "lon": -58.3816, "dj_talk": "regular"}))' "$DIR" "$NAME" "$LANG_" "$VOICE")
docker run -d --name "rdj-$NAME" --network rdj-net \
  -v "$HOME/Música:/music:ro" -p 127.0.0.1:$UI:7710 -p 127.0.0.1:$ST:7702 \
  -e RDJ_ENCODER=libmp3lame -e CFG="$CFG" radio-dj-test \
  sh -c 'mkdir -p ~/.radio-dj && printf "%s" "$CFG" > ~/.radio-dj/config.json && exec radio-dj serve'
echo "UI: http://localhost:$UI  ·  stream: http://localhost:$ST/stream.mp3"
