"""Los dos reproductores de la radio detrás de una sola interfaz: el de mpv (emisoras locales) y el de Spotify.

Nunca suenan los dos: al cambiar de fuente se detiene el otro. Mientras una emisora de Spotify arranca, el mpv de la
música toca la estática; la saca el primer `al_sonar` de Spotify (si Spotify sigue siendo el activo)."""
import threading
from pathlib import Path

from cassette_fm.biblioteca import Estacion


class Reproductores:
    def __init__(self, local, spotify=None, estatica: Path | None = None):
        self._local = local
        self._spotify = spotify
        self._estatica = estatica
        self._activo = local
        self._lock = threading.RLock()
        self.al_cambiar_pista = None
        self.al_fallar = None
        self.al_cambiar_agenda = None     # solo Spotify: empezó o terminó un pedido (la cola de la app)
        self.al_encolado = None
        local.al_cambiar_pista = self._cambio
        local.al_fallar = self._falla
        if spotify is not None:
            spotify.al_cambiar_pista = self._cambio
            spotify.al_fallar = self._falla
            spotify.al_sonar = self._sono_spotify
            spotify.al_cambiar_agenda = lambda *a: self.al_cambiar_agenda and self.al_cambiar_agenda(*a)
            spotify.al_encolado = lambda *a: self.al_encolado and self.al_encolado(*a)

    @property
    def pista_actual(self):
        return self._activo.pista_actual

    def sintonizar(self, estacion: Estacion) -> None:
        with self._lock:
            if estacion.fuente == "spotify":
                if self._spotify is None:
                    raise ValueError(f"la emisora {estacion.nombre!r} es de Spotify y Spotify no está configurado")
                if self._activo is self._spotify:
                    self._spotify.detener()          # de Spotify a Spotify: que no siga sonando la anterior
                else:
                    self._local.detener()
                    self._local.atenuar(1.0)         # si el DJ estaba hablando, la estática va a volumen pleno
                if self._estatica is not None:
                    self._local.estatica(self._estatica)
                self._activo = self._spotify
                self._spotify.sintonizar(estacion)
            else:
                if self._activo is self._spotify:
                    self._spotify.detener()
                    self._spotify.atenuar(1.0)       # la bajada del DJ no queda pegada para la próxima vez
                self._activo = self._local
                self._local.sintonizar(estacion)

    def detener(self) -> None:
        with self._lock:
            if self._activo is self._spotify:
                self._spotify.detener()
                self._spotify.atenuar(1.0)
            self._local.detener()
            self._activo = self._local

    def volumen(self, valor: int) -> int:
        if self._spotify is not None:
            self._spotify.volumen(valor)
        return self._local.volumen(valor)

    def atenuar(self, factor: float, segundos: float = 0.0) -> None:
        self._activo.atenuar(factor, segundos)

    def posicion(self) -> float | None:
        return self._activo.posicion()

    def asegurar(self) -> None:
        self._local.asegurar()

    def actualizar(self, estacion: Estacion) -> None:
        """El rescan: la emisora que suena con sus pistas nuevas (solo le importa a Spotify, que sigue los pedidos)."""
        with self._lock:
            if self._activo is self._spotify:
                self._spotify.actualizar(estacion)

    def _sono_spotify(self) -> None:
        with self._lock:
            if self._activo is self._spotify and self._estatica is not None:
                self._local.estatica(None)

    def _cambio(self, pista, estacion) -> None:
        if self.al_cambiar_pista is not None:
            self.al_cambiar_pista(pista, estacion)

    def _falla(self, estacion, motivo=None) -> None:
        if self.al_fallar is not None:
            self.al_fallar(estacion, motivo)
