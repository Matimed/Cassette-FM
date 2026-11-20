#!/usr/bin/env python3
"""Renderiza el ícono de cassette-fm (branding/casete.png sobre un cuadrado naranja) a los PNG que se usan, con Chromium
sin ventana: favicon e ícono táctil de la web del relay, e ícono del applet. Uso: python3 scripts/renderizar-icono.py"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = RAIZ / "branding" / "casete.png"
FONDO = "#d9822b"
DESTINOS = [  # (archivo, lado en px)
    (RAIZ / "relay/web/favicon-32.png", 32),
    (RAIZ / "relay/web/apple-touch-icon.png", 180),
    (RAIZ / "applet/cassette-fm@cassette-fm/icon.png", 256),
]


def renderizar(lado: int, salida: Path) -> None:
    chromium = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if not chromium:
        sys.exit("hace falta chromium (o google-chrome) para renderizar")
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "i.html"
        html.write_text(
            f'<body style="margin:0;background:transparent"><div style="width:{lado}px;height:{lado}px;background:{FONDO};'
            f'border-radius:22%;display:flex;align-items:center;justify-content:center">'
            f'<img src="{FUENTE.as_uri()}" style="width:80%;display:block"></div></body>')
        subprocess.run([chromium, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                        "--default-background-color=00000000", f"--window-size={lado},{lado}", f"--screenshot={salida}", html.as_uri()],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


if __name__ == "__main__":
    for archivo, lado in DESTINOS:
        renderizar(lado, archivo)
        print(f"{archivo.relative_to(RAIZ)} ({lado}x{lado})")
