import argparse
import http.client
import dataclasses
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from cassette_fm import __version__, applet, atajos, config

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


def _llamar(puerto: int, metodo: str, ruta: str, cuerpo: dict | None = None, timeout: float = 10):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else (
        b"" if metodo == "POST" else None)
    req = urllib.request.Request(f"http://127.0.0.1:{puerto}{ruta}", data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
    sub.add_parser("atajos", help="registra los atajos de teclado en Cinnamon")
    sub.add_parser("applet", help="instala el applet del panel de Cinnamon")
    for nombre in ACCIONES:
        sub.add_parser(nombre, parents=[comun])
    sub.add_parser("status", parents=[comun], help="qué está sonando")
    sub.add_parser("list", parents=[comun], help="lista las estaciones")
    tune = sub.add_parser("tune", parents=[comun], help="sintoniza una estación")
    tune.add_argument("nombre", nargs="+")
    vol = sub.add_parser("vol", parents=[comun], help="volumen: N, +N o -N")
    vol.add_argument("valor")
    spotify = sub.add_parser("spotify", help="Spotify como fuente de emisoras: sesión y estado")
    spotify_sub = spotify.add_subparsers(dest="accion", required=True)
    spotify_sub.add_parser("login", help="abre el navegador para darle permiso a cassette-fm en tu cuenta")
    spotify_sub.add_parser("estado", help="la sesión de Spotify y los temas de cada emisora de Spotify")
    dj = sub.add_parser("dj", help="el DJ: ver el estado, probar un clip o pedir una intervención")
    dj_sub = dj.add_subparsers(dest="accion", required=True)
    dj_sub.add_parser("estado", parents=[comun], help="qué tiene programado el DJ")
    probar = dj_sub.add_parser("probar", parents=[comun], help="registra un clip de prueba en el próximo hueco")
    probar.add_argument("--audio", help="audio a usar (por defecto, un clip de tonos)")
    probar.add_argument("--en", type=float, default=20.0, help="segundos mínimos de antelación (20)")
    pedir = dj_sub.add_parser("pedir", parents=[comun],
                              help="le pide una intervención real al servicio DJ para el próximo hueco")
    pedir.add_argument("--en", type=float, default=20.0, help="segundos mínimos de antelación (20)")
    modo = dj_sub.add_parser("modo", parents=[comun],
                             help="muestra o cambia cómo redacta el DJ: plantillas (por defecto) o llm")
    modo.add_argument("nuevo", nargs="?", choices=["plantillas", "llm"])
    return parser


def _imprimir_planificador(p) -> None:
    if not p:
        return
    if p["servicio"] == "ok":
        print("servicio DJ: ok")
    else:
        espera = f" · reintento en {p['proximo_intento_en']:.0f} s" if p.get("proximo_intento_en") else ""
        print(f"servicio DJ: no responde ({p['error']}){espera}")
    if p.get("en_curso"):
        print(f"pedido en curso: {p['en_curso']['estacion']} ({p['en_curso']['estado']})")


def _ejecutar_dj(args, puerto: int) -> None:
    if args.accion == "estado":
        e = _llamar(puerto, "GET", "/dj")
        if not e["activo"]:
            print("DJ apagado")
            return
        desfase = f"{e['desfase_segundos']:.1f} s" if e["desfase_segundos"] is not None else "—"
        print(f"DJ activo · habla: {'sí' if e['hablando'] else 'no'} · desfase: {desfase}")
        for i in e["intervenciones"]:
            print(f"  {i['estacion']} · en {i['en_segundos']:.0f} s · {i['duracion']:.1f} s · {i['texto']}")
        _imprimir_planificador(e.get("planificador"))
    elif args.accion == "modo":
        r = _llamar(puerto, "GET" if args.nuevo is None else "POST", "/dj/modo",
                    None if args.nuevo is None else {"modo": args.nuevo})
        extra = ""
        if args.nuevo == "llm":
            extra = {"ok": " (el LLM responde)",
                     "falta el modelo": " (¡el modelo no está descargado! corré scripts/instalar-llm.sh; hasta "
                                        "entonces las frases salen por plantillas)"}.get(
                r.get("llm"), " (¡el LLM no responde! las frases van a salir por plantillas hasta que arranque Ollama)")
        print(f"Modo del DJ: {r['modo']}{extra}.")
        if r["modo"] == "llm":
            print("(vuelve a plantillas al reiniciar el servicio DJ)")
    elif args.accion == "pedir":
        r = _llamar(puerto, "POST", "/dj/pedir", {"en_segundos": args.en})
        print(f"Se le pidió una intervención al servicio DJ para «{r['tema']}» en {r['estacion']}: "
              f"va a hablar en {r['en_segundos']:.0f} s si está lista a tiempo.")
    else:
        audio = str(Path(args.audio).resolve()) if args.audio else None
        cuerpo = {"en_segundos": args.en}
        if audio:
            cuerpo["audio"] = audio
        r = _llamar(puerto, "POST", "/dj/probar", cuerpo)
        tema = Path(r["pista_destino"]).stem
        print(f"El DJ va a hablar en {r['en_segundos']:.0f} s, justo después de que arranque «{tema}» "
              f"en {r['estacion']}.")


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
    elif args.comando == "dj":
        _ejecutar_dj(args, puerto)
    elif args.comando == "vol":
        v = args.valor
        try:
            cuerpo = {"delta": int(v)} if v[0] in "+-" else {"valor": int(v)}
        except ValueError:
            raise _ErrorCli(f"volumen inválido: {v!r} (usá N, +N o -N)")
        print(_linea_estado(_llamar(puerto, "POST", "/volumen", cuerpo)))
    else:
        # el rescan relee carpetas y playlists de Spotify (cada una con su timeout): espera bastante más
        espera = 120 if args.comando == "rescan" else 10
        print(_linea_estado(_llamar(puerto, "POST", f"/{ACCIONES[args.comando]}", timeout=espera)))


def _instalar_atajos() -> int:
    ejecutable = shutil.which("cassette")
    if ejecutable is None:
        print("instalá cassette en el PATH primero (scripts/instalar.sh)", file=sys.stderr)
        return 1
    try:
        for mensaje in atajos.instalar(ejecutable, atajos.gsettings):
            print(mensaje)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"no se pudo configurar Cinnamon con gsettings: {e}", file=sys.stderr)
        return 1
    return 0


def _origen_applet() -> Path:
    return Path(__file__).resolve().parents[2] / "applet" / applet.UUID


def _instalar_applet() -> int:
    origen = _origen_applet()
    if not origen.is_dir():
        print(f"no se encuentra el applet en {origen}: corré cassette desde una instalación "
              "en modo editable del repo (scripts/instalar.sh)", file=sys.stderr)
        return 1
    datos = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    try:
        for mensaje in applet.instalar(origen, datos / "cinnamon" / "applets", atajos.gsettings):
            print(mensaje)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"no se pudo instalar el applet: {e}", file=sys.stderr)
        return 1
    return 0


def _spotify(args, cfg, rutas) -> int:
    from cassette_fm.spotify import sesion
    s = sesion.Sesion(rutas.spotify_token, cfg.spotify)
    try:
        if args.accion == "login":
            print("Se abre el navegador: aceptá los permisos de cassette-fm y volvé acá.")
            sesion.login(s, cfg.spotify)
            print("Listo: sesión de Spotify guardada.")
        elif args.accion == "estado":
            return _spotify_estado(cfg, rutas, s)
    except sesion.ErrorSesion as e:
        print(e, file=sys.stderr)
        return 1
    return 0


def _spotify_estado(cfg, rutas, s) -> int:
    from cassette_fm import emisoras, servicio
    from cassette_fm.spotify.api import ClienteSpotify, ErrorSpotify
    try:
        yo = ClienteSpotify(s, cfg.spotify).get("/me")
    except ErrorSpotify as e:
        print(f"Sesión de Spotify: {e}", file=sys.stderr)
        return 1
    print(f"Sesión de Spotify: {yo.get('display_name') or yo.get('id', '?')} ({yo.get('product', '?')})")
    try:
        definidas = emisoras.leer_emisoras(rutas.emisoras, cfg.dj) if rutas.emisoras.exists() else []
    except config.ErrorConfig as e:
        print(e, file=sys.stderr)
        return 1
    catalogo = servicio.catalogo_spotify(cfg, rutas)
    for e in (e for e in definidas if e.fuente.tipo == "spotify"):
        try:
            n = len(catalogo.pistas(e.fuente.valor))
            print(f"«{e.nombre}»: {n} temas (playlist «{catalogo.nombre(e.fuente.valor) or e.fuente.valor}»)")
        except ErrorSpotify as error:
            print(f"«{e.nombre}»: {error}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _armar_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.comando is None:
        parser.print_help()
        return 0
    if args.comando == "atajos":
        return _instalar_atajos()
    if args.comando == "applet":
        return _instalar_applet()
    rutas = config.rutas()
    try:
        cfg = config.cargar_config(rutas.config)
    except config.ErrorConfig as e:
        print(e, file=sys.stderr)
        return 1
    if args.comando == "spotify":
        return _spotify(args, cfg, rutas)
    if args.comando == "serve":
        from cassette_fm import servicio
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        if hasattr(args, "puerto"):
            cfg = dataclasses.replace(cfg, puerto=args.puerto)
        try:
            servicio.servir(cfg, rutas)
        except config.ErrorConfig as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    try:
        _ejecutar(args, getattr(args, "puerto", cfg.puerto))
    except _ErrorCli as e:
        print(e, file=sys.stderr)
        return 1
    return 0
