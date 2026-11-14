import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from cassette_fm import __version__
from cassette_fm.config import ErrorConfig
from cassette_fm.dj import sintetizador as sint
from cassette_fm.dj.config import cargar_config_dj, rutas_dj
from cassette_fm.dj.guiones import RegistroGuiones
from cassette_fm.dj.pedido import IDIOMAS
from cassette_fm.dj.texto_voz import preparar


def _armar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cassette-dj")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="comando")
    sub.add_parser("serve", help="levanta el servicio DJ")
    sub.add_parser("modelos", help="baja los modelos de Kokoro que falten")
    sub.add_parser("voces", help="lista las voces disponibles")
    g = sub.add_parser("guiones", help="muestra los últimos guiones")
    g.add_argument("--ultimos", type=int, default=10)
    v = sub.add_parser("voz-prueba", help="vuelve a sintetizar los últimos guiones con otras voces")
    v.add_argument("--voz", action="append", required=True, help="nombre de la voz (se puede repetir)")
    v.add_argument("--ultimos", type=int, default=5)
    v.add_argument("--salida", default="voz-prueba")
    v.add_argument("--idioma", choices=["es", "en"])
    return parser


def _guiones(rutas, args) -> int:
    registros = RegistroGuiones(rutas.guiones).ultimos(args.ultimos)
    if not registros:
        print("No hay guiones todavía.")
        return 0
    for r in registros:
        try:
            cuando = datetime.fromisoformat(r["ts"]).strftime("%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            cuando = "?"
        texto = r.get("texto") or f"(error: {r.get('error', '?')})"
        marca = " [descartado]" if r.get("descartado") else ""
        print(f"{cuando} · {r.get('estacion', '?')} · {r.get('voz', '?')} · {texto}{marca}")
    return 0


def _voz_prueba(config, rutas, args, sintetizador, fonemizar) -> int:
    validos = [g for g in RegistroGuiones(rutas.guiones).ultimos(1_000_000)
               if g.get("marcado") and g.get("texto") and not g.get("descartado") and not g.get("error")
               and g.get("idioma") in IDIOMAS]
    if args.idioma:
        validos = [g for g in validos if g["idioma"].startswith(args.idioma)]
    elegidos = validos[-args.ultimos:] if args.ultimos > 0 else []
    if not elegidos:
        print("No hay guiones para probar: generá intervenciones con el servicio o revisá `cassette-dj guiones`.",
              file=sys.stderr)
        return 1
    salida = Path(args.salida)
    sintetizador = sintetizador or sint.Sintetizador(config)
    fonemizar = fonemizar or sint.fonemizador()
    try:
        for i, g in enumerate(elegidos, 1):
            lang = IDIOMAS[g["idioma"]]
            prep = preparar(g["marcado"], lang, fonemizar)
            print(f"{i:02d} · {prep.texto}")
            for voz in args.voz:
                destino = salida / f"{i:02d}-{voz}.wav"
                sintetizador.sintetizar(prep.fonemas, voz, lang, destino)
                print(f"     {destino}")
    except (sint.ErrorModelos, ValueError) as e:
        print(f"No se pudo sintetizar: {e}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None, *, sintetizador=None, fonemizar=None) -> int:
    parser = _armar_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.comando is None:
        parser.print_help()
        return 0
    rutas = rutas_dj()
    try:
        config = cargar_config_dj(rutas.config)
    except ErrorConfig as e:
        print(e, file=sys.stderr)
        return 1
    if args.comando == "serve":
        from cassette_fm.dj.servidor import servir
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        try:
            servir(config, rutas)
        except ErrorConfig as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    if args.comando == "modelos":
        if not sint.faltan_modelos(config.modelos_dir):
            print(f"Los modelos ya están en {config.modelos_dir}.")
            return 0
        try:
            sint.descargar_modelos(config.modelos_dir)
        except OSError as e:
            print(f"No se pudieron bajar los modelos: {e}", file=sys.stderr)
            return 1
        print(f"Modelos listos en {config.modelos_dir}.")
        return 0
    if args.comando == "voces":
        try:
            print("\n".join((sintetizador or sint.Sintetizador(config)).voces()))
        except sint.ErrorModelos as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    if args.comando == "guiones":
        return _guiones(rutas, args)
    return _voz_prueba(config, rutas, args, sintetizador, fonemizar)
