"""Acceso de los oyentes: clave (`APP_PASSWORD`), sesión por cookie firmada y límite de intentos fallidos."""
import hashlib
import hmac
import time
from collections import deque
from collections.abc import Callable

DURACION_SESION = 180 * 24 * 3600


def clave_igual(dada: str | None, esperada: str) -> bool:
    """Compara en tiempo constante; una clave vacía nunca coincide."""
    if not dada or not esperada:
        return False
    return hmac.compare_digest(dada.encode(), esperada.encode())


class Acceso:
    def __init__(self, clave: str, reloj: Callable[[], float] = time.time, max_fallos: int = 5,
                 ventana: float = 60.0, bloqueo: float = 60.0):
        self._clave = clave
        self._llave = hashlib.sha256(b"cassette-relay-sesion:" + clave.encode()).digest()
        self._reloj = reloj
        self._max_fallos = max_fallos
        self._ventana = ventana
        self._bloqueo = bloqueo
        self._fallos: deque[float] = deque()
        self._bloqueado_hasta = 0.0

    def _firma(self, vence: int) -> str:
        return hmac.new(self._llave, str(vence).encode(), hashlib.sha256).hexdigest()

    def nueva_sesion(self) -> str:
        vence = int(self._reloj()) + DURACION_SESION
        return f"{vence}.{self._firma(vence)}"

    def sesion_valida(self, valor: str | None) -> bool:
        if not valor:
            return False
        partes = valor.split(".")
        if len(partes) != 2 or not partes[0].isdigit():
            return False
        vence = int(partes[0])
        return hmac.compare_digest(partes[1].encode(), self._firma(vence).encode()) and vence > self._reloj()

    def probar(self, clave: str | None) -> str:
        """"ok", "mal" o "bloqueado". Bloqueado vale también para la clave correcta."""
        ahora = self._reloj()
        if ahora < self._bloqueado_hasta:
            return "bloqueado"
        if clave_igual(clave, self._clave):
            return "ok"
        while self._fallos and self._fallos[0] <= ahora - self._ventana:
            self._fallos.popleft()
        self._fallos.append(ahora)
        if len(self._fallos) >= self._max_fallos:
            self._bloqueado_hasta = ahora + self._bloqueo
            self._fallos.clear()
        return "mal"
