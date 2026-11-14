import json
import threading
from datetime import datetime
from pathlib import Path


class RegistroGuiones:
    """Registro permanente (JSON por línea) de todo lo que el DJ dijo, para repetirlo tal cual en las pruebas de voz."""

    def __init__(self, archivo: Path):
        self._archivo = Path(archivo)
        self._lock = threading.Lock()

    def anotar(self, **campos) -> None:
        linea = json.dumps({"ts": datetime.now().astimezone().isoformat(timespec="seconds"), **campos},
                           ensure_ascii=False, default=str)
        with self._lock:
            self._archivo.parent.mkdir(parents=True, exist_ok=True)
            with open(self._archivo, "a", encoding="utf-8") as f:
                f.write(linea + "\n")

    def ultimos(self, n: int) -> list[dict]:
        if n <= 0:
            return []
        try:
            lineas = self._archivo.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        registros = []
        for linea in lineas:
            try:
                d = json.loads(linea)
            except ValueError:
                continue
            if isinstance(d, dict):
                registros.append(d)
        return registros[-n:]
