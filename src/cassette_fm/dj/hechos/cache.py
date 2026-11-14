import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

_log = logging.getLogger("cassette_fm")


class CacheHechos:
    """Caché persistente (SQLite) de hechos, con vencimiento; guarda también los "no se encontró" (valor None).

    Si la base no se puede abrir o está corrupta, avisa una vez y sigue solo en memoria."""

    def __init__(self, archivo: Path | None, reloj: Callable[[], float] = time.time):
        self._reloj = reloj
        self._lock = threading.RLock()
        self._memoria: dict[str, tuple[str, float]] = {}
        self._claves: dict[str, threading.Lock] = {}
        self._db: sqlite3.Connection | None = None
        self._avisado = False
        if archivo is not None:
            try:
                Path(archivo).parent.mkdir(parents=True, exist_ok=True)
                db = sqlite3.connect(str(archivo), check_same_thread=False, timeout=5.0)
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE IF NOT EXISTS hechos (clave TEXT PRIMARY KEY, valor TEXT NOT NULL, vence REAL NOT NULL)")
                db.commit()
                self._db = db
            except (sqlite3.Error, OSError) as e:
                self._avisar(f"no se puede abrir la caché de hechos {archivo} ({e}): sigue solo en memoria")

    def _avisar(self, mensaje: str) -> None:
        if not self._avisado:
            self._avisado = True
            _log.warning(mensaje)

    def _fallo_de_base(self, e: Exception) -> None:
        self._avisar(f"falló la caché de hechos ({e}): sigue solo en memoria")
        try:
            self._db.close()
        except Exception:
            pass
        self._db = None

    def obtener(self, clave: str) -> tuple[bool, object | None]:
        with self._lock:
            ahora = self._reloj()
            fila = None
            if self._db is not None:
                try:
                    fila = self._db.execute("SELECT valor, vence FROM hechos WHERE clave = ?", (clave,)).fetchone()
                except sqlite3.Error as e:
                    self._fallo_de_base(e)
            if fila is None:
                fila = self._memoria.get(clave)
            if fila is None:
                return False, None
            valor, vence = fila
            if vence <= ahora:
                self._borrar(clave)
                return False, None
            try:
                return True, json.loads(valor)
            except ValueError:
                self._borrar(clave)
                return False, None

    def _borrar(self, clave: str) -> None:
        self._memoria.pop(clave, None)
        if self._db is not None:
            try:
                self._db.execute("DELETE FROM hechos WHERE clave = ?", (clave,))
                self._db.commit()
            except sqlite3.Error as e:
                self._fallo_de_base(e)

    def guardar(self, clave: str, valor: object | None, vigencia_segundos: float) -> None:
        texto = json.dumps(valor, ensure_ascii=False)
        vence = self._reloj() + vigencia_segundos
        with self._lock:
            self._memoria[clave] = (texto, vence)
            if self._db is not None:
                try:
                    self._db.execute("INSERT OR REPLACE INTO hechos (clave, valor, vence) VALUES (?, ?, ?)",
                                     (clave, texto, vence))
                    self._db.commit()
                except sqlite3.Error as e:
                    self._fallo_de_base(e)

    def consultar(self, clave: str, vigencia: Callable[[object | None], float],
                  buscar: Callable[[], object | None]) -> object | None:
        """Devuelve lo vigente o llama UNA vez a `buscar()` (aunque varios hilos pidan lo mismo a la vez)."""
        with self._lock:
            candado = self._claves.setdefault(clave, threading.Lock())
        with candado:
            hay, valor = self.obtener(clave)
            if hay:
                return valor
            valor = buscar()
            self.guardar(clave, valor, vigencia(valor))
            return valor
