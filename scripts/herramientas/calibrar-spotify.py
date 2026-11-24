#!/usr/bin/env python3
"""Calibra el volumen de las emisoras de Spotify contra las locales y propone `ajuste_volumen_db` para [spotify].

    .venv/bin/python scripts/herramientas/calibrar-spotify.py [--local "Nombre"] [--spotify "Nombre"] [--segundos 15]

Con la radio corriendo: sintoniza una emisora local, graba ~15 s solo de su stream (parec), hace lo mismo con una
de Spotify, compara el nivel medio (dB, sin contar los silencios) y vuelve a dejar la radio como estaba.
Suena por los parlantes mientras mide."""
import argparse
import json
import math
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_TASA = 8000
_VENTANA = 400               # muestras (50 ms)
_SILENCIO_DB = -50.0         # ventanas más bajas que esto no cuentan (pausas, fundidos)


def nivel_db(crudo: bytes) -> float | None:
    """Nivel medio (dBFS, potencia promedio) de PCM s16le mono, ignorando las ventanas en silencio."""
    n = len(crudo) // 2
    muestras = struct.unpack(f"<{n}h", crudo[: n * 2])
    potencias = []
    for i in range(0, n - _VENTANA + 1, _VENTANA):
        bloque = muestras[i:i + _VENTANA]
        p = sum(m * m for m in bloque) / len(bloque) / 32768 ** 2
        if p > 0 and 10 * math.log10(p) > _SILENCIO_DB:
            potencias.append(p)
    if not potencias:
        return None
    return 10 * math.log10(sum(potencias) / len(potencias))


def sugerir_ajuste(local_db: float, spotify_db: float, actual: float) -> float:
    """El `ajuste_volumen_db` que iguala Spotify con la local (redondeado a 0,5 y dentro de ±30)."""
    return max(-30.0, min(30.0, round((actual + local_db - spotify_db) * 2) / 2))


def _api(puerto: int, metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else (b"" if metodo == "POST" else None)
    req = urllib.request.Request(f"http://127.0.0.1:{puerto}{ruta}", data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _stream(nombre_app: str, timeout: float = 15) -> int:
    fin = time.time() + timeout
    while time.time() < fin:
        for s in json.loads(subprocess.check_output(["pactl", "-f", "json", "list", "sink-inputs"])):
            p = s.get("properties") or {}
            if p.get("application.name") == nombre_app and not s.get("corked"):
                return s["index"]
        time.sleep(0.3)
    raise SystemExit(f"no encontré el audio de {nombre_app} sonando")


def _grabar(indice: int, segundos: float) -> bytes:
    p = subprocess.run(["timeout", str(segundos), "parec", f"--monitor-stream={indice}", "--format=s16le",
                        f"--rate={_TASA}", "--channels=1", "--raw"], capture_output=True)
    return p.stdout


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from cassette_fm import config as cfg_mod
    from cassette_fm.emisoras import leer_emisoras
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("--local")
    a.add_argument("--spotify")
    a.add_argument("--segundos", type=float, default=15.0)
    args = a.parse_args()
    rutas = cfg_mod.rutas()
    config = cfg_mod.cargar_config(rutas.config)
    emisoras = leer_emisoras(rutas.emisoras, config.dj)
    local = args.local or next((e.nombre for e in emisoras if e.fuente.tipo == "carpeta"), None)
    spotify = args.spotify or next((e.nombre for e in emisoras if e.fuente.tipo == "spotify"), None)
    if not local or not spotify:
        print("Hace falta una emisora local y una de Spotify en estaciones.json.", file=sys.stderr)
        return 1
    puerto = config.puerto
    antes = _api(puerto, "GET", "/estado")
    niveles = {}
    try:
        for nombre, app in ((local, "mpv"), (spotify, "Spotify")):
            print(f"Midiendo «{nombre}» ({args.segundos:g} s)…", flush=True)
            _api(puerto, "POST", "/sintonizar", {"estacion": nombre})
            time.sleep(4 if app == "Spotify" else 2)          # que pase la estática
            niveles[nombre] = nivel_db(_grabar(_stream(app), args.segundos))
            print(f"  {niveles[nombre]:.1f} dB" if niveles[nombre] is not None else "  (silencio)", flush=True)
    finally:
        if antes.get("encendida") and antes.get("estacion"):
            _api(puerto, "POST", "/sintonizar", {"estacion": antes["estacion"]})
        else:
            _api(puerto, "POST", "/apagar")
    if None in niveles.values():
        print("No se pudo medir (¿sonaba algo?). Probá de nuevo.", file=sys.stderr)
        return 1
    ajuste = sugerir_ajuste(niveles[local], niveles[spotify], config.spotify.ajuste_volumen_db)
    print(f"\nLocal «{local}»: {niveles[local]:.1f} dB · Spotify «{spotify}»: {niveles[spotify]:.1f} dB")
    print(f"Poné en {rutas.config}:\n\n[spotify]\najuste_volumen_db = {ajuste:g}\n\n"
          f"y reiniciá la radio: systemctl --user restart cassette-fm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
