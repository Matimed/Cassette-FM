import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

_log = logging.getLogger("cassette_fm")


@dataclass(frozen=True)
class Intervencion:
    id: str
    estacion: str
    inicio: float          # epoch en que empieza a sonar la voz (inicio del tema destino + retraso)
    duracion: float
    audio: Path
    texto: str
    pista_destino: str     # clave (Pista.clave) del tema que arranca justo antes de la voz
    peticion: str | None = None   # "antes"/"despues" si anuncia una petición: no se descarta si cambia la agenda

    @property
    def fin(self) -> float:
        return self.inicio + self.duracion


class RegistroIntervenciones:
    """Intervenciones reservadas en la agenda de cada estación; persisten en un JSON."""

    def __init__(self, archivo: Path, dir_clips: Path, reloj: Callable[[], float] = time.time,
                 gracia_segundos: float = 0.0):
        """`gracia_segundos`: cuánto se conserva una intervención después de su fin por el reloj. La voz se ancla
        al inicio real del tema, que puede estar atrasado respecto del reloj más que la duración del clip."""
        self._gracia = gracia_segundos
        self._archivo = Path(archivo)
        self._dir_clips = Path(dir_clips)
        self._reloj = reloj
        self._lock = threading.RLock()
        self._items: list[Intervencion] = self._cargar()
        self.limpiar()

    def agregar(self, i: Intervencion) -> None:
        with self._lock:
            for otra in self._items:
                if otra.estacion == i.estacion and i.inicio < otra.fin and otra.inicio < i.fin:
                    raise ValueError(f"la intervención se superpone con otra de {i.estacion!r} "
                                     f"({otra.inicio:.0f}–{otra.fin:.0f})")
            self._items.append(i)
            self._guardar()

    def todas(self) -> list[Intervencion]:
        with self._lock:
            return sorted(self._items, key=lambda i: i.inicio)

    def de_la_estacion(self, estacion: str) -> list[Intervencion]:
        ahora = self._reloj()
        return [i for i in self.todas() if i.estacion == estacion and i.fin > ahora]

    def candidatas(self, estacion: str) -> list[Intervencion]:
        """Las que todavía pueden dispararse por el inicio real del tema: vigentes o dentro de la gracia."""
        ahora = self._reloj()
        return [i for i in self.todas() if i.estacion == estacion and i.fin + self._gracia > ahora]

    def activa(self, estacion: str, instante: float) -> Intervencion | None:
        with self._lock:
            for i in self._items:
                if i.estacion == estacion and i.inicio <= instante < i.fin:
                    return i
        return None

    def limpiar(self) -> list[Intervencion]:
        """Quita las vencidas, borra sus clips (solo los que están en el directorio de clips) y persiste."""
        with self._lock:
            ahora = self._reloj()
            vencidas = [i for i in self._items if i.fin + self._gracia <= ahora]
            if not vencidas:
                return []
            self._items = [i for i in self._items if i.fin + self._gracia > ahora]
            for i in vencidas:
                self._borrar_clip(i)
            self._guardar()
            return sorted(vencidas, key=lambda i: i.inicio)

    def quitar_estacion(self, estacion: str, salvo_peticiones: bool = False) -> list[Intervencion]:
        """Quita las de una estación (la agenda cambió) y borra sus clips; persiste. Con `salvo_peticiones`,
        las que anuncian una petición quedan (están ancladas a su tema, que sigue valiendo)."""
        with self._lock:
            quitadas = [i for i in self._items
                        if i.estacion == estacion and not (salvo_peticiones and i.peticion)]
            if not quitadas:
                return []
            self._items = [i for i in self._items if i not in quitadas]
            for i in quitadas:
                self._borrar_clip(i)
            self._guardar()
            return sorted(quitadas, key=lambda i: i.inicio)

    def _borrar_clip(self, i: Intervencion) -> None:
        try:
            if i.audio.resolve().parent == self._dir_clips.resolve():
                i.audio.unlink(missing_ok=True)
        except OSError:
            _log.warning("no se pudo borrar el clip %s", i.audio)

    def _cargar(self) -> list[Intervencion]:
        try:
            crudo = json.loads(self._archivo.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            _log.warning("registro de intervenciones ilegible (%s): se empieza vacío", e)
            return []
        items = []
        for d in crudo if isinstance(crudo, list) else []:
            try:
                i = Intervencion(id=str(d["id"]), estacion=d["estacion"], inicio=float(d["inicio"]),
                                 duracion=float(d["duracion"]), audio=Path(d["audio"]),
                                 texto=d["texto"], pista_destino=d["pista_destino"],
                                 peticion=d.get("peticion") if d.get("peticion") in ("antes", "despues") else None)
            except (KeyError, TypeError, ValueError):
                _log.warning("entrada inválida en el registro de intervenciones: se descarta")
                continue
            if i.audio.exists():
                items.append(i)
        return items

    def _guardar(self) -> None:
        self._archivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._archivo.with_suffix(self._archivo.suffix + ".tmp")
        datos = [{**asdict(i), "audio": str(i.audio)} for i in self._items]
        tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._archivo)
