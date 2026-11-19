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
            "toggle": "alternar", "mute": "silenciar", "rescan": "rescan"}


class _ErrorCli(Exception):
    pass


class _ServicioCaido(_ErrorCli):
    """El servicio no está corriendo (nadie escucha en el puerto)."""


def _linea_estado(estado: dict) -> str:
    vol = f"(vol {estado['volumen']})"
    if not estado["encendida"]:
        return f"⏹ apagada {vol}"
    pista = f" — {estado['pista']}" if estado.get("pista") else ""
    fuente = " · Spotify" if estado.get("fuente") == "spotify" else ""
    return f"▶ {estado['estacion']}{fuente}{pista} {vol}"


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
            raise _ServicioCaido("cassette-fm no está corriendo. Arrancalo con: "
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
    nueva = sub.add_parser("nueva", parents=[comun],
                           help="crea una emisora de Spotify con una playlist tuya y la sintoniza")
    nueva.add_argument("nombre", help="el nombre de la emisora (entre comillas si tiene espacios)")
    nueva.add_argument("playlist", help="el link o la URI de la playlist")
    nueva.add_argument("--voz", help="un alias de [voces] de cassette-dj (por defecto, uno libre al azar)")
    nueva.add_argument("--idioma", choices=["es", "en"], help="el idioma del DJ (por defecto, el de la voz)")
    nueva.add_argument("--icono", help="una imagen PNG, JPG o SVG para el logo (se copia a la carpeta de la config)")
    borrar = sub.add_parser("borrar", parents=[comun], help="saca una emisora de estaciones.json (pregunta antes)")
    borrar.add_argument("nombre", help="el nombre de la emisora (sin importar mayúsculas)")
    borrar.add_argument("--si", action="store_true", help="no preguntar")
    renombrar = sub.add_parser("renombrar", parents=[comun], help="le cambia el nombre a una emisora")
    renombrar.add_argument("nombre", help="el nombre actual (sin importar mayúsculas)")
    renombrar.add_argument("nuevo", help="el nombre nuevo")
    icono = sub.add_parser("icono", parents=[comun], help="le pone o le saca el logo a una emisora")
    icono.add_argument("nombre", help="el nombre de la emisora (sin importar mayúsculas)")
    icono.add_argument("ruta", nargs="?", help="una imagen PNG, JPG o SVG (se copia a la carpeta de la config)")
    icono.add_argument("--quitar", action="store_true", help="sacarle el logo (el archivo no se borra)")
    voces = sub.add_parser("voces", help="las voces con alias que puede usar una emisora nueva")
    voces.add_argument("--json", action="store_true", help="en JSON (para el applet)")
    lan = sub.add_parser("lan", help="la radio por la red: dirección y clave para otra PC (o `regenerar` la clave)")
    lan.add_argument("accion", nargs="?", choices=["regenerar"])
    nube = sub.add_parser("nube", help="el puente a un relay en la nube: estado de la conexión y clave para el relay "
                                       "(o `regenerar` la clave)")
    nube.add_argument("accion", nargs="?", choices=["regenerar"])
    claves = sub.add_parser("claves", help="las claves para escuchar la radio desde el relay en la nube: sin "
                                           "argumentos las lista; `nueva` y `borrar` las administran")
    claves_sub = claves.add_subparsers(dest="accion")
    nueva_clave = claves_sub.add_parser("nueva", help="crea una clave (se muestra una sola vez)")
    nueva_clave.add_argument("nombre", help="para quién es (entre comillas si tiene espacios)")
    permiso = nueva_clave.add_mutually_exclusive_group()
    permiso.add_argument("--escucha", action="store_const", const="escucha", dest="permiso",
                         help="solo escuchar (por defecto)")
    permiso.add_argument("--completa", action="store_const", const="completa", dest="permiso",
                         help="escuchar y cambiar de emisora")
    borrar_clave = claves_sub.add_parser("borrar", help="borra una clave: quien la usaba queda afuera")
    borrar_clave.add_argument("nombre", help="el nombre de la clave (sin importar mayúsculas)")
    borrar_clave.add_argument("--si", action="store_true", help="no preguntar")
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
                             help="muestra o cambia cómo redacta el DJ: plantillas (por defecto), llm o "
                                  "apagado (la radio sigue sin locutor)")
    modo.add_argument("nuevo", nargs="?", choices=["plantillas", "llm", "apagado"])
    return parser


def _imprimir_planificador(p) -> None:
    if not p:
        return
    if p.get("apagado"):
        print("locutor apagado (para prenderlo: cassette dj modo plantillas o llm)")
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
        elif r["modo"] == "apagado":
            print("La radio sigue sin locutor y no le pide nada al servicio DJ, que suelta la voz y el LLM de la "
                  "memoria en unos minutos. Queda así aunque reinicies; para prenderlo: cassette dj modo plantillas "
                  "(o llm).")
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


def _lan(args, cfg, rutas) -> int:
    from cassette_fm import lan_acceso
    token = (lan_acceso.regenerar_token(rutas.lan_token) if args.accion == "regenerar"
             else lan_acceso.leer_o_crear_token(rutas.lan_token))
    if args.accion == "regenerar":
        print("Clave nueva: rige enseguida y corta a los oyentes conectados (la vieja ya no sirve).")
    elif not cfg.lan.activo:
        print("La radio por la red está apagada: poné `activo = true` en la sección [lan] de config.toml y "
              "reiniciá el servicio.")
    direccion = lan_acceso.direccion_para_mostrar(cfg.lan.escuchar)
    print(f"Dirección: http://{direccion}:{cfg.lan.puerto}")
    print(f"Clave:     {token}")
    return 0


def _claves(args, cfg, rutas) -> int:
    """Crea, borra y lista las claves del relay (`claves.json`); el servicio se las pasa al relay solo."""
    from cassette_fm import claves
    try:
        if args.accion == "nueva":
            clave, registro = claves.crear(rutas.claves, args.nombre, args.permiso or "escucha")
            queda = ("escuchar y cambiar de emisora" if registro["permiso"] == "completa" else "solo escuchar")
            print(f"Clave para {registro['nombre']} ({registro['permiso']}: {queda}):")
            print(f"    {clave}")
            print("Anotala ahora: no se vuelve a mostrar (solo se guarda su huella).")
            if not cfg.nube.activo:
                print("El puente a la nube está apagado: las claves rigen cuando actives [nube] en config.toml.")
        elif args.accion == "borrar":
            registro = next((r for r in claves.leer(rutas.claves)
                             if r["nombre"].strip().casefold() == args.nombre.strip().casefold()), None)
            if registro is None:
                raise claves.ErrorClaves(f"no hay ninguna clave con el nombre «{args.nombre.strip()}»")
            if not args.si:
                if not sys.stdin.isatty():
                    print(f"para borrar la clave de «{registro['nombre']}» sin preguntar, agregá --si",
                          file=sys.stderr)
                    return 1
                try:
                    respuesta = input(f"¿Borro la clave de «{registro['nombre']}» ({registro['permiso']})? "
                                      f"Quien la use queda afuera. (s/N) ")
                except EOFError:
                    respuesta = ""
                if respuesta.strip().casefold() not in _SI:
                    print("No se borró nada.")
                    return 1
            claves.borrar(rutas.claves, registro["nombre"])
            print(f"✗ {registro['nombre']} · la clave ya no sirve")
        else:
            lista = claves.leer(rutas.claves)
            if not lista:
                print("No hay claves. Creá una con `cassette claves nueva NOMBRE`; "
                      "la maestra (MASTER_PASSWORD del relay) siempre funciona.")
            for r in lista:
                print(f"{r['nombre']:<24} {r['permiso']:<9} {r['creada'][:10]}")
    except claves.ErrorClaves as e:
        print(e, file=sys.stderr)
        return 1
    return 0


def _duracion(segundos: float) -> str:
    if segundos < 60:
        return f"{int(segundos)} s"
    if segundos < 3600:
        return f"{int(segundos // 60)} min"
    return f"{int(segundos // 3600)} h {int(segundos % 3600 // 60)} min"


def _nube(args, cfg, rutas) -> int:
    from cassette_fm import lan_acceso
    token = (lan_acceso.regenerar_token(rutas.nube_token) if args.accion == "regenerar"
             else lan_acceso.leer_o_crear_token(rutas.nube_token))
    if args.accion == "regenerar":
        print("Clave nueva: el puente se reconecta con ella enseguida. Cargala también en el relay (la vieja ya no "
              "sirve).")
    if not cfg.nube.activo:
        print("El puente a la nube está apagado: poné `activo = true` y `url = \"wss://…\"` (la del relay) en la "
              "sección [nube] de config.toml y reiniciá el servicio.")
    else:
        print(f"Relay:     {cfg.nube.url}")
        try:
            nube = _llamar(cfg.puerto, "GET", "/estado").get("nube")
        except (_ServicioCaido, _ErrorCli) as e:
            print(f"Conexión:  ? ({e})")
        else:
            if nube is None:
                print("Conexión:  el servicio corre sin el puente (reinicialo para que tome la config)")
            elif nube.get("conectado"):
                subiendo = ", ".join(str(k) for k in nube.get("subiendo") or [])
                hace = nube.get("conectado_hace")
                desde = f" hace {_duracion(hace)}" if hace is not None else ""
                print(f"Conexión:  conectado{desde} · subiendo: "
                      f"{subiendo + ' kbps' if subiendo else 'nada (sin oyentes)'}")
            else:
                print("Conexión:  sin conexión con el relay (se reintenta solo; mirá journalctl --user -u cassette-fm)")
                if nube.get("error"):
                    print(f"Último error: {nube['error']}")
    print(f"Clave:     {token}")
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


def _hoy():
    import datetime
    return datetime.date.today()


def _estado_soloist(c) -> None:
    """Soloist: si responde, si tiene sesión y si es el dispositivo activo; y cuánto le queda al build (90 días)."""
    import datetime
    import re
    import subprocess
    import threading
    from cassette_fm.spotify.api import ErrorSpotify
    from cassette_fm.spotify.soloist import ClienteSoloist
    auth: dict = {}
    llego = threading.Event()

    def evento(e):
        if e.get("type") == "auth_state":
            auth.update(e)
            llego.set()
    cliente = ClienteSoloist(c.soloist_ws, al_evento=evento)
    try:
        cliente.conectar(2)
        cliente.comando("get_auth_state")
        if llego.wait(2):
            si = lambda v: "sí" if v else "no"      # noqa: E731
            print(f"Soloist: corriendo · sesión: {si(auth.get('logged_in'))} · activo: {si(auth.get('is_active'))}")
        else:
            print("Soloist: corriendo, pero no contestó el estado de la sesión")
    except ErrorSpotify as e:
        print(f"Soloist: no responde ({e}) — systemctl --user status cassette-soloist")
    finally:
        cliente.cerrar()
    try:
        version = subprocess.run([str(c.soloist_bin), "--version"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        print(f"Soloist: no está instalado en {c.soloist_bin} (scripts/instalar-spotify.sh)")
        return
    m = re.search(r"\((\d{8})\)", version)
    if not m:
        return
    vence = datetime.datetime.strptime(m.group(1), "%Y%m%d").date() + datetime.timedelta(days=90)
    dias = (vence - _hoy()).days
    if dias < 14:
        print(f"⚠ Soloist vence en {dias} días: corré scripts/actualizar-soloist.sh")
    else:
        print(f"Soloist build {m.group(1)}: vence en {dias} días")


def _spotify_estado(cfg, rutas, s) -> int:
    from cassette_fm import emisoras, servicio
    from cassette_fm.spotify.api import ClienteSpotify, ErrorSpotify
    _estado_soloist(cfg.spotify)
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


def _nueva(args, cfg, rutas, puerto: int) -> int:
    """Valida todo antes de escribir: nombre libre, link de playlist, voz y que Spotify deje leer la playlist (que
    queda en la caché: el rescan de la radio no la vuelve a bajar)."""
    from cassette_fm import emisora_nueva, emisoras, servicio
    from cassette_fm.dj.config import cargar_config_dj, rutas_dj
    from cassette_fm.spotify.api import ErrorSpotify
    try:
        definidas = emisora_nueva.leer_crudo(rutas.emisoras)
        emisoras.leer_emisoras(rutas.emisoras, cfg.dj)     # si ya está roto, la radio no la vería: no se toca
        nombre = emisora_nueva.chequear_nombre(definidas, args.nombre)
        playlist = emisoras.playlist_de(args.playlist)
        if playlist is None:
            raise config.ErrorConfig(f"«{args.playlist}» no es el link de una playlist de Spotify")
        archivo_dj = rutas_dj().config
        alias = cargar_config_dj(archivo_dj).voces if archivo_dj.exists() else {}
        eleccion = emisora_nueva.elegir_voz(alias, emisora_nueva.voces_en_uso(definidas), args.idioma, args.voz)
        dj = {"idioma": eleccion.idioma, "voz": eleccion.voz}
        config.campos_dj(rutas.emisoras, dj, f'"{nombre}".dj.', cfg.dj)   # lo que la radio aceptará al leerla
        pistas = servicio.catalogo_spotify(cfg, rutas).pistas(playlist)
        if not pistas:
            raise config.ErrorConfig("la playlist está vacía (o no tiene temas que se puedan reproducir)")
        icono = emisora_nueva.copiar_icono(Path(args.icono), rutas.emisoras.parent) if args.icono else None
    except (config.ErrorConfig, ErrorSpotify) as e:
        print(e, file=sys.stderr)
        return 1
    emisora_nueva.guardar(rutas.emisoras, definidas, {
        "nombre": nombre, "fuente": {"spotify": args.playlist.strip()},
        "dj": dj, **({"icono": icono} if icono else {})})
    repetida = " (otra emisora ya usa esta voz: no quedaban libres)" if eleccion.repetida else ""
    print(f"✓ {nombre} ({len(pistas)} temas) · DJ: {eleccion.voz} ({eleccion.idioma}){repetida}")
    try:
        _llamar(puerto, "POST", "/rescan", timeout=120)
    except _ServicioCaido as e:
        print(f"La emisora quedó guardada y aparece cuando arranque la radio ({e})")
        return 0
    except _ErrorCli as e:
        print(f"La emisora quedó guardada, pero la radio no pudo releer las emisoras: {e}", file=sys.stderr)
        return 1
    try:
        print(_linea_estado(_llamar(puerto, "POST", "/sintonizar", {"estacion": nombre})))
    except _ErrorCli as e:
        print(f"La emisora quedó guardada, pero la radio no la pudo sintonizar: {e}", file=sys.stderr)
        return 1
    return 0


_SI = ("s", "si", "sí", "y", "yes")


def _borrar(args, rutas, puerto: int) -> int:
    """Saca una emisora de `estaciones.json` (preguntando antes, salvo con --si) y le pide a la radio que relea."""
    from cassette_fm import emisora_nueva
    try:
        emisoras = emisora_nueva.leer_crudo(rutas.emisoras)
        i = emisora_nueva.buscar(emisoras, args.nombre)
    except config.ErrorConfig as e:
        print(e, file=sys.stderr)
        return 1
    nombre = emisoras[i]["nombre"].strip()
    if not args.si:
        if not sys.stdin.isatty():
            print(f"para borrar «{nombre}» sin preguntar, agregá --si", file=sys.stderr)
            return 1
        try:
            respuesta = input(f"¿Borro «{nombre}» ({emisora_nueva.describir(emisoras[i])})? (s/N) ")
        except EOFError:
            respuesta = ""
        if respuesta.strip().casefold() not in _SI:
            print("No se borró nada.")
            return 1
    emisora_nueva.escribir(rutas.emisoras, emisoras[:i] + emisoras[i + 1:])
    print(f"✗ {nombre} · ya no está en estaciones.json")
    try:
        print(_linea_estado(_llamar(puerto, "POST", "/rescan", timeout=120)))
    except _ServicioCaido:
        print("La radio no está corriendo: el cambio se ve al prenderla.")
    except _ErrorCli as e:
        print(f"La emisora quedó borrada, pero la radio no pudo releer las emisoras: {e}", file=sys.stderr)
        return 1
    return 0


def _icono(args, rutas, puerto: int) -> int:
    """Le pone (copiando la imagen a `iconos/`) o le saca el logo a una emisora; nunca borra archivos de `iconos/`
    (otra emisora puede usar el mismo)."""
    from cassette_fm import emisora_nueva
    if bool(args.ruta) == args.quitar:
        print("indicá la imagen o --quitar (una de las dos)", file=sys.stderr)
        return 1
    try:
        emisoras = emisora_nueva.leer_crudo(rutas.emisoras)
        i = emisora_nueva.buscar(emisoras, args.nombre)
        relativa = None if args.quitar else emisora_nueva.copiar_icono(Path(args.ruta), rutas.emisoras.parent)
    except config.ErrorConfig as e:
        print(e, file=sys.stderr)
        return 1
    emisora = {k: v for k, v in emisoras[i].items() if k != "icono"}
    if relativa:
        emisora["icono"] = relativa
    emisoras[i] = emisora
    emisora_nueva.escribir(rutas.emisoras, emisoras)
    print(f"🖼 {emisora['nombre'].strip()} · {relativa or 'sin logo'}")
    try:
        _llamar(puerto, "POST", "/rescan", timeout=120)
    except _ServicioCaido:
        print("La radio no está corriendo: el cambio se ve al prenderla.")
    except _ErrorCli as e:
        print(f"El logo quedó guardado, pero la radio no pudo releer las emisoras: {e}", file=sys.stderr)
        return 1
    return 0


def _renombrar(args, rutas, puerto: int) -> int:
    """Le cambia el nombre a una emisora; si sonaba, la radio la vuelve a sintonizar con el nombre nuevo (el orden de
    los temas sale del nombre: queda en otro punto, como una emisora nueva)."""
    from cassette_fm import emisora_nueva
    try:
        emisoras = emisora_nueva.leer_crudo(rutas.emisoras)
        i = emisora_nueva.buscar(emisoras, args.nombre)
        nuevo = emisora_nueva.chequear_nombre(emisoras[:i] + emisoras[i + 1:], args.nuevo)
    except config.ErrorConfig as e:
        print(e, file=sys.stderr)
        return 1
    viejo = emisoras[i]["nombre"].strip()
    if nuevo == viejo:
        print(f"«{viejo}» ya se llama así.")
        return 0
    try:
        antes = _llamar(puerto, "GET", "/estado")
    except _ServicioCaido:
        antes = None
    except _ErrorCli as e:
        print(e, file=sys.stderr)
        return 1
    emisoras[i] = dict(emisoras[i], nombre=nuevo)
    emisora_nueva.escribir(rutas.emisoras, emisoras)
    print(f"✎ {viejo} → {nuevo}")
    if antes is None:
        print("La radio no está corriendo: el cambio se ve al prenderla.")
        return 0
    try:
        estado = _llamar(puerto, "POST", "/rescan", timeout=120)
        if antes.get("encendida") and antes.get("estacion") == viejo:     # el rescan sola la mandaría a la primera
            estado = _llamar(puerto, "POST", "/sintonizar", {"estacion": nuevo})
    except _ErrorCli as e:
        print(f"El nombre quedó cambiado, pero la radio no pudo releer las emisoras: {e}", file=sys.stderr)
        return 1
    print(_linea_estado(estado))
    return 0


def _voces(args, rutas) -> int:
    from cassette_fm import emisora_nueva
    from cassette_fm.dj.config import cargar_config_dj, rutas_dj
    try:
        definidas = emisora_nueva.leer_crudo(rutas.emisoras) if rutas.emisoras.exists() else []
        archivo_dj = rutas_dj().config
        alias = cargar_config_dj(archivo_dj).voces if archivo_dj.exists() else {}
    except config.ErrorConfig as e:
        print(e, file=sys.stderr)
        return 1
    voces = emisora_nueva.voces_disponibles(alias, definidas)
    if args.json:
        print(json.dumps(voces, ensure_ascii=False))
        return 0
    if not voces:
        print("no hay voces con alias: se definen en [voces] del config de cassette-dj (cassette-dj voces las lista)")
    for v in voces:
        print(f"{v['alias']:<12} {v['voz']:<28} {v['idioma']:<6} {', '.join(v['emisoras'])}".rstrip())
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
    if args.comando == "lan":
        return _lan(args, cfg, rutas)
    if args.comando == "nube":
        return _nube(args, cfg, rutas)
    if args.comando == "claves":
        return _claves(args, cfg, rutas)
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
    if args.comando == "nueva":
        return _nueva(args, cfg, rutas, getattr(args, "puerto", cfg.puerto))
    if args.comando == "voces":
        return _voces(args, rutas)
    if args.comando == "borrar":
        return _borrar(args, rutas, getattr(args, "puerto", cfg.puerto))
    if args.comando == "icono":
        return _icono(args, rutas, getattr(args, "puerto", cfg.puerto))
    if args.comando == "renombrar":
        return _renombrar(args, rutas, getattr(args, "puerto", cfg.puerto))
    try:
        _ejecutar(args, getattr(args, "puerto", cfg.puerto))
    except _ErrorCli as e:
        print(e, file=sys.stderr)
        return 1
    return 0
