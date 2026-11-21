#!/usr/bin/env python3
"""Separa los logos de una imagen (uno o varios sobre un mismo fondo) y deja cada uno
como PNG cuadrado de 512 px con fondo transparente, listo para el dial de cassette-fm.

Uso:
    /usr/bin/python3 recortar_iconos.py IMAGEN --nombres frecuencia-gris,lets-rave,black-heart
    /usr/bin/python3 recortar_iconos.py IMAGEN --nombres a,b --salida /tmp/prueba

Los logos se numeran de izquierda a derecha y, si hay varias filas, de arriba hacia abajo.
Necesita Pillow, numpy y scipy (están en el python del sistema, no en el .venv del proyecto).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage as ndi

SALIDA_POR_DEFECTO = Path.home() / ".config" / "cassette-fm" / "iconos"
LADO = 512


def fondo_y_primer_plano(rgb: np.ndarray, umbral: int):
    """El fondo es el color mediano del borde de la imagen; primer plano = lo que se aparta de él."""
    borde = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).reshape(-1, 3)
    fondo = np.median(borde, axis=0)
    dif = np.abs(rgb.astype(int) - fondo.astype(int)).max(axis=2)
    return fondo, dif > umbral


def ordenar(centros, alturas):
    """Índices ordenados por filas (arriba→abajo) y, dentro de cada fila, izquierda→derecha.

    Dos logos son de la misma fila si sus centros verticales difieren menos que media altura de logo
    (los logos de una misma tira suelen estar a alturas algo distintas).
    """
    ys = [c[0] for c in centros]
    xs = [c[1] for c in centros]
    tolerancia = 0.5 * float(np.median(alturas))
    filas = []
    for i in sorted(range(len(centros)), key=lambda i: ys[i]):
        if filas and abs(ys[i] - np.mean([ys[j] for j in filas[-1]])) <= tolerancia:
            filas[-1].append(i)
        else:
            filas.append([i])
    return [i for fila in filas for i in sorted(fila, key=lambda k: xs[k])]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("imagen")
    p.add_argument("--nombres", help="nombres de archivo (sin .png), separados por coma, en el orden de lectura")
    p.add_argument("--salida", default=str(SALIDA_POR_DEFECTO), help="carpeta de salida")
    p.add_argument("--cantidad", type=int, help="cuántos logos esperás (por defecto, los que se detecten)")
    p.add_argument("--umbral", type=int, default=48, help="diferencia con el fondo para contar como logo (48)")
    p.add_argument("--contorno", type=int, help="px de contorno a recuperar: 8 sobre fondo oscuro, 2 sobre claro")
    p.add_argument("--previa", help="carpeta donde guardar una vista previa sobre gris y una tira con todos")
    p.add_argument("--sobrescribir", action="store_true", help="pisar archivos que ya existan")
    a = p.parse_args()

    src = Image.open(a.imagen).convert("RGB")
    rgb = np.array(src)
    fondo, primer = fondo_y_primer_plano(rgb, a.umbral)
    oscuro = fondo.mean() < 80
    contorno = a.contorno if a.contorno is not None else (8 if oscuro else 2)
    escala = max(src.size) / 2752  # los parámetros están afinados para ~2750 px de ancho
    it_union = max(int(12 * escala), 2)
    contorno = max(int(round(contorno * escala)), 0)

    primer = ndi.binary_opening(primer, iterations=1)
    unido = ndi.binary_closing(primer, structure=np.ones((3, 3)), iterations=it_union)
    relleno = ndi.binary_fill_holes(unido)
    lab, n = ndi.label(relleno)
    if n == 0:
        sys.exit("No encontré ningún logo: probá con --umbral más bajo.")
    areas = np.array(ndi.sum(relleno, lab, range(1, n + 1)))
    if a.cantidad:
        elegidos = list(np.argsort(areas)[::-1][: a.cantidad])
    else:
        elegidos = [i for i in range(n) if areas[i] >= 0.2 * areas.max()]
    centros = [ndi.center_of_mass(relleno, lab, i + 1) for i in elegidos]
    alturas = [np.ptp(np.where(lab == i + 1)[0]) + 1 for i in elegidos]
    elegidos = [elegidos[i] for i in ordenar(centros, alturas)]

    nombres = [s.strip() for s in a.nombres.split(",")] if a.nombres else [f"logo-{i + 1}" for i in range(len(elegidos))]
    if len(nombres) != len(elegidos):
        sys.exit(f"Detecté {len(elegidos)} logo(s) pero pasaste {len(nombres)} nombre(s). "
                 f"Revisá la vista previa con --previa y ajustá --cantidad/--nombres/--umbral.")

    salida = Path(a.salida).expanduser()
    previa = Path(a.previa).expanduser() if a.previa else None
    for d in (salida, previa):
        if d:
            d.mkdir(parents=True, exist_ok=True)
    existentes = [n for n in nombres if (salida / f"{n}.png").exists()]
    if existentes and not a.sobrescribir:
        sys.exit(f"Ya existen en {salida}: {', '.join(existentes)}. Elegí otros nombres o usá --sobrescribir.")

    estruc = ndi.generate_binary_structure(2, 1)
    hechos, tira = [], []
    for nombre, i in zip(nombres, elegidos):
        m = lab == i + 1
        if contorno:
            m = ndi.binary_fill_holes(ndi.binary_dilation(m, structure=estruc, iterations=contorno))
        ys, xs = np.where(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        alfa = Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(max(1.2 * escala, 0.6)))
        rgba = src.convert("RGBA")
        rgba.putalpha(alfa)
        rgba = rgba.crop((x0, y0, x1, y1))
        lado = max(rgba.size) + int(16 * escala)
        lienzo = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        lienzo.paste(rgba, ((lado - rgba.width) // 2, (lado - rgba.height) // 2))
        final = lienzo.resize((LADO, LADO), Image.LANCZOS)
        destino = salida / f"{nombre}.png"
        final.save(destino)
        hechos.append({"nombre": nombre, "archivo": str(destino), "caja_en_origen": [int(x0), int(y0), int(x1), int(y1)]})
        gris = Image.new("RGBA", (LADO, LADO), (200, 200, 200, 255))
        gris.alpha_composite(final)
        tira.append(gris.convert("RGB"))
        if previa:
            gris.convert("RGB").save(previa / f"{nombre}.png")

    if previa:
        hoja = Image.new("RGB", (LADO * len(tira), LADO))
        for k, im in enumerate(tira):
            hoja.paste(im, (k * LADO, 0))
        hoja.save(previa / "tira.png")
    print(json.dumps({"fondo": [int(c) for c in fondo], "iconos": hechos}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
