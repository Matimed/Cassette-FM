#!/usr/bin/env python3
"""Escucha el WebSocket de Soloist y escribe cada evento (JSON, uno por línea) en un archivo. Solo lee: no manda
ningún comando, así que no cambia lo que está sonando.

    .venv/bin/python scripts/herramientas/capturar-cola-soloist.py SALIDA.jsonl [--url ws://127.0.0.1:9787] [--segundos 300]

Sirve para ver qué manda Soloist al encolar temas desde la app de Spotify (queue_changed, track_changed)."""
import argparse
import json
import sys
import time

from websockets.sync.client import connect


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("salida")
    a.add_argument("--url", default="ws://127.0.0.1:9787")
    a.add_argument("--segundos", type=float, default=300.0)
    args = a.parse_args()
    fin = time.monotonic() + args.segundos
    n = 0
    with connect(args.url, open_timeout=5) as ws, open(args.salida, "w", encoding="utf-8") as f:
        print(f"Escuchando {args.url} durante {args.segundos:g} s (Ctrl+C para cortar)…", flush=True)
        try:
            while time.monotonic() < fin:
                try:
                    crudo = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                evento = json.loads(crudo)
                f.write(json.dumps({"t": time.time(), "evento": evento}, ensure_ascii=False) + "\n")
                f.flush()
                n += 1
                if evento.get("type") in ("queue_changed", "track_changed"):
                    print(f"  {evento.get('type')}", flush=True)
        except KeyboardInterrupt:
            pass
    print(f"{n} eventos en {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
