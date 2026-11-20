#!/usr/bin/env python3
"""Renderiza los íconos de cassette-fm a partir de branding/casete.png (contorno negro sobre transparente), con Chromium sin
ventana: el casete en blanco con la ventana de la cinta (los carretes) en naranja, solo o sobre un fondo oscuro, y el blanco
liso del panel del applet. Uso: python3 scripts/renderizar-icono.py"""
import base64
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = RAIZ / "branding" / "casete.png"
BLANCO, NARANJA = "#f4f4f7", "#d9822b"
FONDO_OSCURO = "linear-gradient(#2c2c3a, #0e0e13)"
# la ventana de la cinta dentro del PNG de 512 px (el casete va al 78 %, con la antena arriba): x 118..391, y 256..366
# (no toca ninguna otra línea del dibujo)
VENTANA = "inset(50.1% 23.6% 28.6% 23.1%)"

# (archivo, lado en px, fondo o None, esquinas redondeadas en %, tamaño del casete respecto del lado, ventana en naranja, color base)
DESTINOS = [
    (RAIZ / "relay/web/casete-color.png", 512, None, 0, 1.0, True, BLANCO),
    (RAIZ / "relay/web/favicon-32.png", 32, FONDO_OSCURO, 22, 0.95, True, BLANCO),
    (RAIZ / "relay/web/apple-touch-icon.png", 180, FONDO_OSCURO, 0, 0.88, True, BLANCO),
    (RAIZ / "applet/cassette-fm@cassette-fm/icon.png", 256, FONDO_OSCURO, 22, 0.95, True, BLANCO),
    # la app instalada en Android: "any" (esquinas redondeadas) y "maskable" (a sangre completa, con el casete dentro de la zona segura)
    (RAIZ / "relay/web/icono-192.png", 192, FONDO_OSCURO, 22, 0.95, True, BLANCO),
    (RAIZ / "relay/web/icono-512.png", 512, FONDO_OSCURO, 22, 0.95, True, BLANCO),
    (RAIZ / "relay/web/icono-maskable-512.png", 512, FONDO_OSCURO, 0, 0.66, True, BLANCO),
    (RAIZ / "applet/cassette-fm@cassette-fm/casete-panel.png", 128, None, 0, 1.0, False, "#ffffff"),
]


def pagina(lado: int, fondo: str | None, radio: int, escala: float, acento: bool, base: str) -> str:
    uri = "data:image/png;base64," + base64.b64encode(FUENTE.read_bytes()).decode()
    lado_casete = round(lado * escala)
    capa = lambda color, extra="": (f'<div style="position:absolute;inset:0;background:{color};{extra}'
                                    f'-webkit-mask:url({uri}) center/100% 100%;mask:url({uri}) center/100% 100%"></div>')
    capas = capa(base) + (capa(NARANJA, f"clip-path:{VENTANA};") if acento else "")
    marco = f"background:{fondo};" if fondo else ""
    return (f'<body style="margin:0;background:transparent"><div style="width:{lado}px;height:{lado}px;{marco}border-radius:{radio}%;'
            f'display:flex;align-items:center;justify-content:center"><div style="position:relative;width:{lado_casete}px;'
            f'height:{lado_casete}px">{capas}</div></div></body>')


def renderizar(archivo: Path, lado: int, *args) -> None:
    chromium = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if not chromium:
        sys.exit("hace falta chromium (o google-chrome) para renderizar")
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "i.html"
        html.write_text(pagina(lado, *args))
        subprocess.run([chromium, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000", f"--window-size={lado},{lado}", f"--screenshot={archivo}", html.as_uri()],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


if __name__ == "__main__":
    for archivo, lado, fondo, radio, escala, acento, base in DESTINOS:
        renderizar(archivo, lado, fondo, radio, escala, acento, base)
        print(f"{archivo.relative_to(RAIZ)} ({lado}x{lado})")
