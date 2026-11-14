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
    h = sub.add_parser("hechos", help="muestra el clima de ahora y, con --artista y --titulo, los datos del tema")
    h.add_argument("--artista")
    h.add_argument("--titulo")
    h.add_argument("--isrc")
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


def _hechos(config, rutas, args, clientes) -> int:
    if clientes is None:
        from cassette_fm.dj.hechos.cache import CacheHechos
        from cassette_fm.dj.hechos.clima import ClienteClima
        from cassette_fm.dj.hechos.musicbrainz import ClienteMusicBrainz
        cache = CacheHechos(rutas.hechos)
        clientes = (ClienteClima(config, cache), ClienteMusicBrainz(config, cache, version=__version__))
    clima_cliente, musicbrainz = clientes
    clima = clima_cliente.actual() if clima_cliente is not None else None
    if clima is None:
        print("Clima: sin datos (mirá el log del aviso o la conexión).")
    else:
        momento = "de día" if clima.es_de_dia else "de noche"
        print(f"Clima en Buenos Aires: {clima.temperatura} grados, {clima.cielo}, {momento}.")
    if args.artista and musicbrainz is not None:
        tema = musicbrainz.datos_del_tema(args.artista, args.titulo, args.isrc)
        if tema is None:
            print(f"MusicBrainz: sin datos verificados de «{args.titulo}» de {args.artista} "
                  "(sin 'contacto' configurado, sin coincidencia clara o sin conexión).")
        else:
            partes = [f"año {tema.anio}" if tema.anio else None, f"país {tema.pais}" if tema.pais else None,
                      (f"grupo desde {tema.anio_inicio_artista}" if tema.es_grupo and tema.anio_inicio_artista
                       else "grupo" if tema.es_grupo else None)]
            print(f"MusicBrainz: «{args.titulo}» de {args.artista}: {' · '.join(p for p in partes if p)}")
            print(f"  fuente: {tema.fuente}")
    return 0


def main(argv: list[str] | None = None, *, sintetizador=None, fonemizar=None, clientes=None) -> int:
    parser = _armar_parser()
    args = parser.parse_args(argv)
    if args.comando == "hechos" and bool(args.artista) != bool(args.titulo):
        parser.error("--artista y --titulo van juntos")
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
        except (ErrorConfig, sint.ErrorModelos) as e:
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
    if args.comando == "hechos":
        return _hechos(config, rutas, args, clientes)
    return _voz_prueba(config, rutas, args, sintetizador, fonemizar)
