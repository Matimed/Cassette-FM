"""Una emisora nueva en `estaciones.json` (`cassette nueva`): el nombre, la voz del DJ y su idioma.

La voz sale de los alias de `[voces]` del config de cassette-dj: al azar entre los que no usa ninguna emisora, para
que cada una suene distinta. El idioma del DJ se deduce de la voz (una voz de Kokoro o Piper habla un solo idioma)."""
import json
import os
import random
import re
import shutil
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cassette_fm.config import ErrorConfig

_KOKORO = re.compile(r"^([a-z])[fm]_")
_IDIOMA_KOKORO = {"a": "en", "b": "en-gb", "e": "es"}     # el resto (francés, japonés…) la radio no lo habla


@dataclass(frozen=True)
class Eleccion:
    voz: str            # el alias (o la voz cruda si se pidió así)
    idioma: str
    repetida: bool      # ya la usa otra emisora: no quedaban alias libres en ese idioma


def leer_crudo(archivo: Path) -> list[dict]:
    """`estaciones.json` tal como está (para agregarle una emisora sin perder nada)."""
    try:
        datos = json.loads(Path(archivo).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErrorConfig(f"{archivo}: no existe (arrancá la radio una vez para crearlo)") from None
    except json.JSONDecodeError as e:
        raise ErrorConfig(f"{archivo}: línea {e.lineno}, columna {e.colno}: {e.msg}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise ErrorConfig(f"{archivo}: {e}") from None
    if not isinstance(datos, list):
        raise ErrorConfig(f"{archivo}: tiene que ser una lista de emisoras ([{{…}}, {{…}}])")
    return datos


def _normalizar(nombre: str) -> str:
    return unicodedata.normalize("NFC", nombre).casefold()


def chequear_nombre(emisoras: list[dict], nombre: str) -> str:
    """El nombre sin espacios alrededor; error si está vacío o ya lo tiene otra emisora."""
    nombre = nombre.strip()
    if not nombre:
        raise ErrorConfig("la emisora necesita un nombre")
    for e in emisoras:
        otro = e.get("nombre") if isinstance(e, dict) else None
        if isinstance(otro, str) and _normalizar(otro.strip()) == _normalizar(nombre):
            raise ErrorConfig(f"ya hay una emisora que se llama «{otro.strip()}»")
    return nombre


def voces_en_uso(emisoras: list[dict]) -> list[str]:
    voces = []
    for e in emisoras:
        dj = e.get("dj") if isinstance(e, dict) else None
        if isinstance(dj, dict) and isinstance(dj.get("voz"), str):
            voces.append(dj["voz"])
    return voces


def idioma_de_voz(voz: str) -> str | None:
    """El idioma que habla una voz de Kokoro (`ef_dora`) o Piper (`piper:es_AR-…`); en una mezcla, la primera."""
    primera = voz.split("+")[0]
    if primera.startswith("piper:"):
        modelo = primera.removeprefix("piper:")
        if modelo.startswith("es_"):
            return "es"
        if modelo.startswith("en_GB"):
            return "en-gb"
        return "en" if modelo.startswith("en_") else None
    m = _KOKORO.match(primera)
    return _IDIOMA_KOKORO.get(m.group(1)) if m else None


def _base(idioma: str) -> str:
    return idioma.split("-")[0]


def elegir_voz(alias: Mapping[str, str], en_uso: list[str], idioma: str | None = None, voz: str | None = None,
               azar: random.Random | None = None) -> Eleccion:
    """La voz del DJ de la emisora nueva: `voz` si se pidió (alias o voz cruda), si no un alias libre al azar (del
    `idioma` pedido, si hay); sin libres, uno de los menos usados."""
    utiles = {a: i for a, v in alias.items() if (i := idioma_de_voz(v)) is not None}
    if voz is not None:
        propio = utiles.get(voz) if voz in alias else idioma_de_voz(voz)
        if propio is None:
            disponibles = ", ".join(utiles) or "ninguno"
            raise ErrorConfig(f"la voz «{voz}» no existe o no habla inglés ni español (alias: {disponibles})")
        if idioma is not None and _base(propio) != _base(idioma):
            raise ErrorConfig(f"la voz «{voz}» habla {propio}, no {idioma}")
        return Eleccion(voz, propio, False)
    candidatos = [a for a, i in utiles.items() if idioma is None or _base(i) == _base(idioma)]
    if not candidatos:
        donde = "en inglés ni en español" if idioma is None else f"en {idioma}"
        raise ErrorConfig(f"no hay voces con alias {donde}: se definen en [voces] del config de cassette-dj "
                          f"(cassette-dj voces las lista)")
    usos = Counter(en_uso)
    menos = min(usos[a] for a in candidatos)
    elegido = (azar or random).choice([a for a in candidatos if usos[a] == menos])
    return Eleccion(elegido, utiles[elegido], menos > 0)


def voces_disponibles(alias: Mapping[str, str], emisoras: list[dict]) -> list[dict]:
    """Los alias que sirven para una emisora (hablan inglés o español), con su voz, su idioma y las emisoras que ya
    los usan; en el orden del config (para `cassette voces` y el modal del applet)."""
    usos: dict[str, list[str]] = {}
    for e in emisoras:
        dj = e.get("dj") if isinstance(e, dict) else None
        if isinstance(dj, dict) and isinstance(dj.get("voz"), str) and isinstance(e.get("nombre"), str):
            usos.setdefault(dj["voz"], []).append(e["nombre"].strip())
    return [{"alias": a, "voz": v, "idioma": i, "emisoras": usos.get(a, [])}
            for a, v in alias.items() if (i := idioma_de_voz(v)) is not None]


def buscar(emisoras: list[dict], nombre: str) -> int:
    """El índice de la emisora que se llama `nombre` (sin distinguir mayúsculas ni espacios alrededor)."""
    buscado = _normalizar(nombre.strip())
    nombres = []
    for i, e in enumerate(emisoras):
        otro = e.get("nombre") if isinstance(e, dict) else None
        if isinstance(otro, str):
            if _normalizar(otro.strip()) == buscado:
                return i
            nombres.append(otro.strip())
    raise ErrorConfig(f"no hay ninguna emisora que se llame «{nombre.strip()}» (hay: {', '.join(nombres) or 'ninguna'})")


def describir(emisora: dict) -> str:
    """De dónde sale la música de la emisora, para preguntar antes de borrarla."""
    fuente = emisora.get("fuente") if isinstance(emisora, dict) else None
    if isinstance(fuente, dict) and "spotify" in fuente:
        return "Spotify"
    if isinstance(fuente, dict) and isinstance(fuente.get("carpeta"), str):
        return f"carpeta {fuente['carpeta']}"
    return "fuente desconocida"


def escribir(archivo: Path, emisoras: list[dict]) -> None:
    """Reescribe `estaciones.json` con `emisoras` (escritura atómica: nunca queda a medias)."""
    archivo = Path(archivo)
    tmp = archivo.with_name(archivo.name + ".tmp")
    tmp.write_text(json.dumps(emisoras, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, archivo)


_IMAGENES = (".png", ".jpg", ".jpeg", ".svg")


def copiar_icono(origen: Path, base: Path) -> str:
    """Deja el logo en `base/iconos/` y devuelve su ruta relativa a `base` (la que va en `"icono"`): si ya está ahí
    adentro no se copia; si hay otro con el mismo nombre, se reusa si es igual y si no se numera (`power-2.png`). Así
    borrar la imagen original no deja a la emisora sin logo, y la misma imagen para dos emisoras no se duplica."""
    origen = Path(origen).expanduser()
    if origen.suffix.lower() not in _IMAGENES:
        raise ErrorConfig(f"«{origen}»: el logo tiene que ser una imagen PNG, JPG o SVG")
    if not origen.is_file():
        raise ErrorConfig(f"«{origen}»: no existe")
    carpeta = Path(base) / "iconos"
    if origen.resolve().is_relative_to(carpeta.resolve()):
        return origen.resolve().relative_to(Path(base).resolve()).as_posix()
    contenido = origen.read_bytes()
    carpeta.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        nombre = origen.name if n == 1 else f"{origen.stem}-{n}{origen.suffix}"
        destino = carpeta / nombre
        if not destino.exists():
            shutil.copyfile(origen, destino)
            break
        if destino.read_bytes() == contenido:
            break
        n += 1
    return f"iconos/{nombre}"


def guardar(archivo: Path, emisoras: list[dict], nueva: dict) -> None:
    """Reescribe `estaciones.json` con la emisora nueva al final."""
    escribir(archivo, [*emisoras, nueva])
