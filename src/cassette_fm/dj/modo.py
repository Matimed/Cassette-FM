import threading

MODOS = ("plantillas", "llm")


class ModoDJ:
    """Cómo redacta el servicio: con plantillas o con el LLM. Se cambia en caliente y NO se guarda."""

    def __init__(self, inicial: str = "plantillas"):
        self._lock = threading.Lock()
        self._modo = self._validar(inicial)

    @staticmethod
    def _validar(modo) -> str:
        if not isinstance(modo, str) or modo not in MODOS:
            raise ValueError(f"modo inválido {modo!r}: tiene que ser uno de {', '.join(MODOS)}")
        return modo

    def actual(self) -> str:
        with self._lock:
            return self._modo

    def poner(self, modo: str) -> str:
        nuevo = self._validar(modo)
        with self._lock:
            self._modo = nuevo
        return nuevo
