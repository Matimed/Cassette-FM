#!/usr/bin/env python3
"""Ensayo del DJ: manda pedidos reales al servicio DJ para unas cuantas transiciones de cada radio, muestra los
guiones en vivo (con colores) y al final resume qué escribió y qué descartó.

    .venv/bin/python scripts/ensayo-dj.py                       # 5 temas por radio, todas las radios
    .venv/bin/python scripts/ensayo-dj.py --canciones 3 --estacion "Power F.M."
    .venv/bin/python scripts/ensayo-dj.py --modo llm            # además cambia el modo del DJ (hasta reiniciarlo)

Los pedidos son los mismos que arma el planificador de la radio (`armar_pedido`), con la voz, el idioma y la
personalidad de cada radio. Se mandan de a uno para pasar los `recientes` como lo hace el planificador.
"""
import argparse
import collections
import itertools
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from cassette_fm import biblioteca, config as cfg_mod
    from cassette_fm.agenda import secuencia
    from cassette_fm.cliente_dj import ClienteDJ, ErrorDJ
    from cassette_fm.dj.config import rutas_dj
    from cassette_fm.planificacion import Hueco, armar_pedido
except ImportError:      # corrido con otro Python: se reintenta con el del proyecto
    _venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python3"
    if _venv.exists() and Path(sys.executable).absolute() != _venv.absolute():
        os.execv(_venv, [str(_venv), *sys.argv])
    raise

_ANSI = {"hora": "36", "estacion": "1;35", "voz": "2", "ok": "32", "descartado": "31", "plantilla": "33",
         "motivo": "2;33", "titulo": "1", "tenue": "2"}


def pintar(clave: str, texto: str, color: bool) -> str:
    return f"\033[{_ANSI[clave]}m{texto}\033[0m" if color else texto


def clasificar(r: dict) -> str:
    """'ok' (frase del LLM aceptada), 'descartado' (intento del LLM rechazado) o 'plantilla'."""
    if r.get("descartado"):
        return "descartado"
    return "ok" if r.get("fuente") == "llm" else "plantilla"


def linea_guion(r: dict, color: bool) -> str:
    try:
        hora = datetime.fromisoformat(r["ts"]).strftime("%H:%M:%S")
    except (KeyError, ValueError):
        hora = "??:??:??"
    clase = clasificar(r)
    texto = r.get("texto") or r.get("crudo") or f"(sin texto: {r.get('error') or r.get('motivo') or '?'})"
    motivo = r.get("motivo")
    if clase == "ok":
        marca = pintar("ok", f"[llm, recortada: {r['recortado']}]" if r.get("recortado") else "[llm]", color)
    elif clase == "descartado":
        marca = pintar("descartado", f"[descartado: {motivo}]" if motivo else "[descartado]", color)
    else:
        marca = pintar("plantilla", "[plantilla]", color) + (
            " " + pintar("motivo", f"({motivo})", color) if motivo else "")
    if r.get("intento") and r.get("fuente") == "llm":
        marca += pintar("tenue", f" intento {r['intento']}", color)
    cuerpo = pintar({"ok": "ok", "descartado": "descartado", "plantilla": "plantilla"}[clase], texto, color)
    return (f"{pintar('hora', hora, color)} · {pintar('estacion', str(r.get('estacion', '?')), color)} · "
            f"{pintar('voz', str(r.get('voz', '?')), color)}\n    {cuerpo}\n    {marca}")


def armar_pares(estacion, cantidad: int, ahora: float) -> list[tuple]:
    """Pares (anterior, siguiente) consecutivos de la agenda real, solo con temas que tienen artista y título."""
    serie = list(itertools.islice(secuencia(estacion, ahora), cantidad * 3 + 2))
    pares = [(a, s) for (a, _), (s, _) in zip(serie, serie[1:]) if s.artista and s.cancion]
    return pares[:cantidad]


def resumir(registros: list[dict]) -> dict:
    """Totales por estación y los motivos de descarte y de respaldo, de más a menos frecuente."""
    por_estacion: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    motivos: collections.Counter = collections.Counter()
    for r in registros:
        clase = clasificar(r)
        por_estacion[r.get("estacion", "?")][clase] += 1
        if clase != "ok" and r.get("motivo"):
            motivos[(clase, r["motivo"].split(":")[0][:60])] += 1
    return {"por_estacion": {k: dict(v) for k, v in por_estacion.items()}, "motivos": motivos.most_common()}


class Seguidor:
    """Lee lo nuevo de guiones.jsonl (solo líneas completas) y devuelve los registros de un pedido."""

    def __init__(self, archivo: Path):
        self._archivo = archivo
        self._posicion = archivo.stat().st_size if archivo.exists() else 0
        self._resto = ""

    def nuevos(self, id_: str) -> list[dict]:
        try:
            with open(self._archivo, encoding="utf-8") as f:
                f.seek(self._posicion)
                bloque = f.read()
                self._posicion = f.tell()
        except FileNotFoundError:
            return []
        texto = self._resto + bloque
        *completas, self._resto = texto.split("\n")
        registros = []
        for linea in completas:
            try:
                r = json.loads(linea)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("id") == id_:
                registros.append(r)
        return registros


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--canciones", type=int, default=5, help="transiciones por radio (default 5)")
    p.add_argument("--estacion", action="append", help="solo esta radio (se puede repetir)")
    p.add_argument("--margen", type=float, default=300.0,
                   help="segundos entre el pedido y el momento en que 'hablaría' el DJ (default 300; es lo que "
                        "tiene el LLM para escribir)")
    p.add_argument("--modo", choices=["llm", "plantillas"], help="cambia el modo del DJ antes de empezar")
    p.add_argument("--espera", type=float, default=600.0, help="segundos máximos por pedido (default 600)")
    p.add_argument("--conservar-audio", action="store_true", help="no borra los clips que genera")
    p.add_argument("--sin-color", action="store_true")
    p.add_argument("--salida", type=Path, help="dónde guardar los registros (default: carpeta de estado del DJ)")
    return p.parse_args()


def main() -> int:
    args = _argumentos()
    color = not args.sin_color and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    rutas, rutas_d = cfg_mod.rutas(), rutas_dj()
    config = cfg_mod.cargar_config(rutas.config)
    if not config.dj.url:
        print("La config de la radio no tiene [dj] url: no hay servicio DJ al que pedirle.", file=sys.stderr)
        return 1
    cliente = ClienteDJ(config.dj.url, timeout=30.0)
    try:
        if args.modo:
            cliente.poner_modo(args.modo)
        salud = cliente.salud()
    except ErrorDJ as e:
        print(f"No se pudo hablar con el servicio DJ: {e}", file=sys.stderr)
        return 1
    print(f"Servicio DJ: modo {salud.get('modo', '?')}")

    estaciones = [e for e in biblioteca.escanear(config.raiz_musica, rutas.cache) if e.pistas]
    if args.estacion:
        faltan = set(args.estacion) - {e.nombre for e in estaciones}
        if faltan:
            print(f"No existen esas radios: {', '.join(sorted(faltan))}", file=sys.stderr)
            return 1
        estaciones = [e for e in estaciones if e.nombre in args.estacion]
    seguidor = Seguidor(rutas_d.guiones)
    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    registros: list[dict] = []
    ahora = time.time()
    recientes: dict[str, list[str]] = {}
    n = 0
    pendiente = None
    try:
        for estacion in estaciones:
            cfg = cfg_mod.configuracion_dj(config, estacion.nombre)
            pares = armar_pares(estacion, args.canciones, ahora)
            print(f"\n{pintar('estacion', '== ' + estacion.nombre + ' ==', color)} "
                  f"({len(pares)} transiciones · voz {cfg.voz} · {cfg.idioma})")
            for anterior, pista in pares:
                n += 1
                id_ = f"ensayo-{sello}-{n:03d}"
                pedido = armar_pedido(id_, estacion.nombre, Hueco(pista, time.time(), time.time() + args.margen,
                                                                  anterior), cfg, recientes.get(estacion.nombre, []))
                print(f"\n{pintar('tenue', f'{anterior.artista} - {anterior.cancion}', color)}  →  "
                      f"{pintar('titulo', f'{pista.artista} - {pista.cancion}', color)}")
                inicio = time.monotonic()
                cliente.enviar(pedido)
                pendiente = id_
                estado = {}
                while time.monotonic() - inicio < args.espera:
                    for r in seguidor.nuevos(id_):
                        registros.append(r)
                        print(linea_guion(r, color), flush=True)
                    estado = cliente.estado(id_) or {}
                    if estado.get("estado") in ("listo", "error", "cancelado"):
                        break
                    time.sleep(0.5)
                else:
                    estado = {"estado": "error", "error": f"sin respuesta en {args.espera:g} s"}
                    cliente.cancelar(id_)
                for r in seguidor.nuevos(id_):
                    registros.append(r)
                    print(linea_guion(r, color), flush=True)
                pendiente = None
                seg = time.monotonic() - inicio
                if estado.get("estado") == "listo":
                    ing = ", ".join(estado.get("ingredientes") or [])
                    print(pintar("tenue", f"    → listo en {seg:.0f} s · audio {estado.get('duracion') or 0:.1f} s · "
                                          f"[{ing}]", color))
                    nuevos = [x for x in (estado.get("ingredientes") or []) if isinstance(x, str)]
                    todos = recientes.get(estacion.nombre, []) + nuevos
                    recientes[estacion.nombre] = todos[-cfg.recientes_cantidad:] if cfg.recientes_cantidad else []
                else:
                    print(pintar("descartado", f"    → {estado.get('estado')}: {estado.get('error')}", color))
                if not args.conservar_audio:
                    cliente.cancelar(id_)
    except KeyboardInterrupt:
        print("\nInterrumpido.")
        if pendiente:
            cliente.cancelar(pendiente)
    except ErrorDJ as e:
        print(f"\nSe cortó la comunicación con el servicio DJ: {e}", file=sys.stderr)

    destino = args.salida or rutas_d.estado / "ensayos" / f"ensayo-{sello}.jsonl"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in registros), encoding="utf-8")
    resumen = resumir(registros)
    print(f"\n{pintar('titulo', '== Resumen ==', color)}")
    for nombre, c in resumen["por_estacion"].items():
        print(f"  {pintar('estacion', nombre, color)}: "
              f"{pintar('ok', str(c.get('ok', 0)) + ' llm', color)} · "
              f"{pintar('descartado', str(c.get('descartado', 0)) + ' descartados', color)} · "
              f"{pintar('plantilla', str(c.get('plantilla', 0)) + ' plantillas', color)}")
    for (clase, motivo), veces in resumen["motivos"]:
        print(f"  {veces:3d} × {pintar(clase, clase, color)}: {motivo}")
    print(f"\nRegistros completos (prompt, crudo, hechos): {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
