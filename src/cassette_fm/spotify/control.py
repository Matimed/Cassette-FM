"""Qué suena en el dispositivo de Soloist, por la Web API (la posición inicial solo se puede pedir por acá)."""
import threading
from collections.abc import Callable

from cassette_fm.spotify.api import ClienteSpotify, ErrorSpotify


class ControlSpotify:
    def __init__(self, cliente: ClienteSpotify, nombre_dispositivo: str):
        self._cliente = cliente
        self._nombre = nombre_dispositivo
        self._id: str | None = None
        self._lock = threading.Lock()

    def dispositivo(self) -> str:
        """El id del dispositivo de Soloist (por su nombre); se recuerda hasta que deje de servir."""
        with self._lock:
            if self._id is None:
                datos = self._cliente.get("/me/player/devices")
                for d in datos.get("devices") or []:
                    if isinstance(d, dict) and d.get("name") == self._nombre and isinstance(d.get("id"), str):
                        self._id = d["id"]
                        break
                else:
                    raise ErrorSpotify(f"Soloist ({self._nombre}) no aparece como dispositivo de Spotify: ¿está "
                                       f"corriendo y emparejado? (cassette spotify estado)")
            return self._id

    def reproducir(self, uris: list[str], posicion_ms: Callable[[], int]) -> None:
        """Reproduce la lista desde `posicion_ms()` del primero, calculada justo antes del play (cada pedido a la API
        tarda ~0,6 s: con la posición de antes el tema arrancaría atrasado). Shuffle y repeat los apaga antes quien
        llama, por el WebSocket de Soloist (por la API costaban otro ~1,2 s). Si Spotify ya no conoce el dispositivo,
        lo busca de nuevo una vez."""
        try:
            self._reproducir(self.dispositivo(), uris, posicion_ms)
        except ErrorSpotify as e:
            if e.codigo != 404:
                raise
            with self._lock:
                self._id = None
            self._reproducir(self.dispositivo(), uris, posicion_ms)

    def _reproducir(self, dispositivo: str, uris: list[str], posicion_ms: Callable[[], int]) -> None:
        self._cliente.put("/me/player/play", {"device_id": dispositivo},
                          {"uris": list(uris), "position_ms": int(posicion_ms())})
