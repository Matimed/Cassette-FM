"""Playlist de Spotify → pistas de una emisora, con caché por `snapshot_id` (si no cambió, no se baja de nuevo)."""
import json
import logging
import os
import threading
from pathlib import Path

from cassette_fm.biblioteca import Pista
from cassette_fm.spotify.api import ClienteSpotify, ErrorSpotify

_log = logging.getLogger("cassette_fm")


def pista_de(entrada: dict) -> Pista | None:
    """La pista de un ítem de `/playlists/{id}/items`, o None si no se puede escuchar (local, episodio, no
    disponible, sin duración)."""
    if not isinstance(entrada, dict) or entrada.get("is_local"):
        return None
    t = entrada.get("item")
    if not isinstance(t, dict) or t.get("type") != "track" or t.get("is_local") or t.get("is_playable") is False:
        return None
    uri, nombre, ms = t.get("uri"), t.get("name"), t.get("duration_ms")
    if not isinstance(uri, str) or not uri.startswith("spotify:track:") or not isinstance(nombre, str):
        return None
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms <= 0:
        return None
    artistas = [a["name"] for a in t.get("artists") or [] if isinstance(a, dict) and isinstance(a.get("name"), str)]
    artista = ", ".join(artistas) or None
    album = t.get("album") if isinstance(t.get("album"), dict) else {}
    isrc = (t.get("external_ids") or {}).get("isrc") if isinstance(t.get("external_ids"), dict) else None
    return Pista(ruta=None, duracion=ms / 1000, titulo=f"{artista} - {nombre}" if artista else nombre,
                 fuente="spotify", artista=artista, cancion=nombre,
                 album=album.get("name") if isinstance(album.get("name"), str) else None,
                 isrc=isrc if isinstance(isrc, str) else None, uri=uri)


def _a_dict(p: Pista) -> dict:
    return {"uri": p.uri, "duracion": p.duracion, "titulo": p.titulo, "artista": p.artista, "cancion": p.cancion,
            "album": p.album, "isrc": p.isrc}


def _de_dict(d: dict) -> Pista:
    return Pista(ruta=None, duracion=float(d["duracion"]), titulo=d["titulo"], fuente="spotify", artista=d["artista"],
                 cancion=d["cancion"], album=d["album"], isrc=d["isrc"], uri=d["uri"])


class CatalogoSpotify:
    def __init__(self, cliente: ClienteSpotify, archivo_cache: Path):
        self._cliente = cliente
        self._archivo = Path(archivo_cache)
        self._lock = threading.Lock()

    def pistas(self, playlist: str) -> tuple[Pista, ...]:
        """Los temas de la playlist en su orden. Si Spotify falla y hay caché, se usa la caché (con aviso)."""
        with self._lock:
            cache = self._leer_cache()
            guardada = cache.get(playlist)
            try:
                meta = self._cliente.get(f"/playlists/{playlist}", {"fields": "snapshot_id,name"})
                if guardada and guardada.get("snapshot_id") == meta.get("snapshot_id"):
                    return tuple(_de_dict(d) for d in guardada["pistas"])
                nombre = meta.get("name") if isinstance(meta.get("name"), str) else playlist
                pistas = self._bajar(playlist, nombre)
            except ErrorSpotify as e:
                if guardada:
                    _log.warning("Spotify no respondió (%s): la emisora usa los temas guardados de la playlist %s",
                                 e, guardada.get("nombre", playlist))
                    return tuple(_de_dict(d) for d in guardada["pistas"])
                raise
            cache[playlist] = {"snapshot_id": meta.get("snapshot_id"), "nombre": nombre,
                               "pistas": [_a_dict(p) for p in pistas]}
            self._guardar_cache(cache)
            return pistas

    def nombre(self, playlist: str) -> str | None:
        """El nombre de la playlist según la caché (después de `pistas`)."""
        with self._lock:
            return self._leer_cache().get(playlist, {}).get("nombre")

    def _bajar(self, playlist: str, nombre: str) -> tuple[Pista, ...]:
        pistas = []
        try:
            for pagina in self._cliente.paginas(f"/playlists/{playlist}/items", {"limit": 50}):
                for entrada in pagina.get("items") or []:
                    p = pista_de(entrada)
                    if p is not None:
                        pistas.append(p)
        except ErrorSpotify as e:
            if e.codigo in (403, 404):
                raise ErrorSpotify(f"la playlist «{nombre}» no es tuya: Spotify no deja leer sus temas; "
                                   f"copiala a una playlist propia", e.codigo) from None
            raise
        return tuple(pistas)

    def _leer_cache(self) -> dict:
        try:
            datos = json.loads(self._archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(datos, dict):
            return {}
        validas = {}
        for clave, v in datos.items():
            try:
                [_de_dict(d) for d in v["pistas"]]
                validas[clave] = v
            except (TypeError, KeyError, ValueError):
                continue
        return validas

    def _guardar_cache(self, cache: dict) -> None:
        self._archivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._archivo.with_name(self._archivo.name + ".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._archivo)
