#!/bin/sh
# tts-retry.sh <voice> <text> <out> — edge-tts with retries; logs failures to stderr
for i in 1 2 3; do
  edge-tts --voice "$1" --text "$2" --write-media "$3" 2>/tmp/tts-err && exit 0
  sleep 2
done
echo "[tts] failed after 3 tries: $(tail -1 /tmp/tts-err) :: $2" >&2
exit 1
