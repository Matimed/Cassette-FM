import argparse

from cassette_fm import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cassette")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="comando")
    sub.add_parser("serve", help="levanta el servicio")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.comando == "serve":
        from cassette_fm import config, servicio
        r = config.rutas()
        servicio.servir(config.cargar_config(r.config), r)
        return 0
    parser.print_help()
    return 0
