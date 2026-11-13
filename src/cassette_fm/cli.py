import argparse
import http.client
import json
import sys
import urllib.error
import urllib.request

from cassette_fm import __version__, config

ACCIONES = {"next": "siguiente", "prev": "anterior", "on": "encender", "off": "apagar",
            "toggle": "alternar", "rescan": "rescan"}


class _ErrorCli(Exception):
    pass


def _linea_estado(estado: dict) -> str:
    vol = f"(vol {estado['volumen']})"
    if not estado["encendida"]:
        return f"⏹ apagada {vol}"
    pista = f" — {estado['pista']}" if estado.get("pista") else ""
    return f"▶ {estado['estacion']}{pista} {vol}"


def _llamar(puerto: int, metodo: str, ruta: str, cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else (
        b"" if metodo == "POST" else None)
    req = urllib.request.Request(f"http://127.0.0.1:{puerto}{ruta}", data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            mensaje = json.loads(e.read())["error"]
        except (ValueError, KeyError):
            mensaje = f"error {e.code}"
        raise _ErrorCli(mensaje)
    except urllib.error.URLError as e:
        if isinstance(e.reason, (ConnectionRefusedError, FileNotFoundError)):
            raise _ErrorCli("cassette-fm no está corriendo. Arrancalo con: "
                            "systemctl --user start cassette-fm (o cassette serve)")
        raise _ErrorCli(f"no se pudo hablar con cassette-fm: {e.reason}")
    except (ConnectionError, TimeoutError, http.client.HTTPException):
        raise _ErrorCli("el servicio cortó la conexión sin responder "
                        "(mirá: journalctl --user -u cassette-fm -e)")


def _armar_parser() -> argparse.ArgumentParser:
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--puerto", type=int, default=argparse.SUPPRESS,
                       help="puerto del servicio (por defecto, el de config.toml)")
    parser = argparse.ArgumentParser(prog="cassette", parents=[comun])
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="comando")
    sub.add_parser("serve", parents=[comun], help="levanta el servicio")
    for nombre in ACCIONES:
        sub.add_parser(nombre, parents=[comun])
    sub.add_parser("status", parents=[comun], help="qué está sonando")
    sub.add_parser("list", parents=[comun], help="lista las estaciones")
    tune = sub.add_parser("tune", parents=[comun], help="sintoniza una estación")
    tune.add_argument("nombre", nargs="+")
    vol = sub.add_parser("vol", parents=[comun], help="volumen: N, +N o -N")
    vol.add_argument("valor")
    return parser


def _ejecutar(args, puerto: int) -> None:
    if args.comando == "status":
        print(_linea_estado(_llamar(puerto, "GET", "/estado")))
    elif args.comando == "list":
        estado = _llamar(puerto, "GET", "/estado")
        for e in _llamar(puerto, "GET", "/estaciones"):
            actual = estado["encendida"] and e["nombre"] == estado["estacion"]
            print(f"{'▶' if actual else ' '} {e['nombre']} ({e['pistas']} temas)")
    elif args.comando == "tune":
        print(_linea_estado(_llamar(puerto, "POST", "/sintonizar",
                                    {"estacion": " ".join(args.nombre)})))
    elif args.comando == "vol":
        v = args.valor
        try:
            cuerpo = {"delta": int(v)} if v[0] in "+-" else {"valor": int(v)}
        except ValueError:
            raise _ErrorCli(f"volumen inválido: {v!r} (usá N, +N o -N)")
        print(_linea_estado(_llamar(puerto, "POST", "/volumen", cuerpo)))
    else:
        print(_linea_estado(_llamar(puerto, "POST", f"/{ACCIONES[args.comando]}")))


def main(argv: list[str] | None = None) -> int:
    parser = _armar_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.comando is None:
        parser.print_help()
        return 0
    rutas = config.rutas()
    cfg = config.cargar_config(rutas.config)
    if args.comando == "serve":
        from cassette_fm import servicio
        servicio.servir(cfg, rutas)
        return 0
    try:
        _ejecutar(args, getattr(args, "puerto", cfg.puerto))
    except _ErrorCli as e:
        print(e, file=sys.stderr)
        return 1
    return 0
