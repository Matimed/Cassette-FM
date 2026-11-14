import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cassette_fm.dj.pedido import Pedido
from cassette_fm.dj.produccion import Resultado
from cassette_fm.dj.sintetizador import ErrorModelos

_log = logging.getLogger("cassette_fm")
_MANTENIMIENTO_SEGUNDOS = 60.0


class EstadoTrabajo(str, Enum):
    PENDIENTE = "pendiente"
    TRABAJANDO = "trabajando"
    LISTO = "listo"
    ERROR = "error"
    CANCELADO = "cancelado"


@dataclass
class _Trabajo:
    pedido: Pedido
    estado: EstadoTrabajo = EstadoTrabajo.PENDIENTE
    resultado: Resultado | None = None
    error: str | None = None
    terminado_en: float = 0.0


class Cola:
    """Trabajos de producción en hilos propios, en orden de llegada, sin estado entre pedidos."""

    def __init__(self, productor, trabajadores: int = 1, retencion_segundos: float = 3600.0,
                 reloj: Callable[[], float] = time.monotonic):
        self._productor = productor
        self._retencion = retencion_segundos
        self._reloj = reloj
        self._lock = threading.Lock()
        self._trabajos: dict[str, _Trabajo] = {}
        self._pendientes: queue.Queue[str] = queue.Queue()
        self._parar = threading.Event()
        self._hilos = [threading.Thread(target=self._trabajar, daemon=True, name=f"dj-trabajador-{i}")
                       for i in range(trabajadores)]
        self._hilos.append(threading.Thread(target=self._mantener, daemon=True, name="dj-mantenimiento"))
        for h in self._hilos:
            h.start()

    def enviar(self, pedido: Pedido) -> str:
        with self._lock:
            if self._parar.is_set():
                raise RuntimeError("la cola está detenida")
            if pedido.id not in self._trabajos:
                self._trabajos[pedido.id] = _Trabajo(pedido)
                self._pendientes.put(pedido.id)
        return pedido.id

    def estado(self, id: str) -> dict | None:
        with self._lock:
            t = self._trabajos.get(id)
            if t is None:
                return None
            r = t.resultado
            return {"estado": t.estado.value, "duracion": r.duracion if r else None,
                    "texto": r.texto if r else None, "ingredientes": list(r.ingredientes) if r else None,
                    "error": t.error}

    def audio(self, id: str) -> Path | None:
        with self._lock:
            t = self._trabajos.get(id)
            if t is None or t.estado is not EstadoTrabajo.LISTO or t.resultado is None:
                return None
            return t.resultado.audio if t.resultado.audio.exists() else None

    def cancelar(self, id: str) -> bool:
        with self._lock:
            t = self._trabajos.get(id)
            if t is None or t.estado is not EstadoTrabajo.PENDIENTE:
                return False
            t.estado = EstadoTrabajo.CANCELADO
            t.terminado_en = self._reloj()
            return True

    def contadores(self) -> dict[str, int]:
        with self._lock:
            cuenta = {e.value: 0 for e in EstadoTrabajo}
            for t in self._trabajos.values():
                cuenta[t.estado.value] += 1
            return cuenta

    def limpiar(self) -> int:
        terminados = (EstadoTrabajo.LISTO, EstadoTrabajo.ERROR, EstadoTrabajo.CANCELADO)
        with self._lock:
            ahora = self._reloj()
            vencidos = [i for i, t in self._trabajos.items()
                        if t.estado in terminados and ahora - t.terminado_en >= self._retencion]
            quitados = [self._trabajos.pop(i) for i in vencidos]
        for t in quitados:
            if t.resultado is not None:
                t.resultado.audio.unlink(missing_ok=True)
        return len(quitados)

    def detener(self, espera: float = 5.0) -> None:
        self._parar.set()
        fin = time.monotonic() + espera
        for h in self._hilos:
            h.join(max(0.0, fin - time.monotonic()))

    def _trabajar(self) -> None:
        while not self._parar.is_set():
            try:
                id_ = self._pendientes.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._lock:
                t = self._trabajos.get(id_)
                if t is None or t.estado is not EstadoTrabajo.PENDIENTE:
                    continue
                t.estado = EstadoTrabajo.TRABAJANDO
            try:
                resultado, estado, error = self._productor.producir(t.pedido), EstadoTrabajo.LISTO, None
            except (ValueError, ErrorModelos) as e:
                resultado, estado, error = None, EstadoTrabajo.ERROR, str(e)
            except Exception:
                _log.exception("error inesperado al producir la intervención %s", id_)
                resultado, estado, error = (None, EstadoTrabajo.ERROR,
                                            "error interno al producir la intervención (mirá el log del servicio)")
            with self._lock:
                t.resultado, t.estado, t.error, t.terminado_en = resultado, estado, error, self._reloj()

    def _mantener(self) -> None:
        while not self._parar.wait(_MANTENIMIENTO_SEGUNDOS):
            self.limpiar()
