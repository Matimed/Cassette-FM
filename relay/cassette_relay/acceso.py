"""Acceso de los oyentes: la clave maestra (`MASTER_PASSWORD`), las claves de la PC (por huella), la sesión por cookie
firmada y el límite de intentos fallidos. Docs: docs/superpowers/specs/2026-11-19-claves-relay-design.md."""
import hashlib
import hmac
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from .config import MAESTRA

DURACION_SESION = 180 * 24 * 3600
PERMISOS = ("escucha", "completa")
_ID = re.compile(r"[0-9a-f]{8}")
_HUELLA = re.compile(r"[0-9a-f]{64}")
_MAX_CLAVES = 200
_MAX_DIGITOS_VENCE = 12


@dataclass(frozen=True)
class Identidad:
    """Con qué clave se entró (`MAESTRA` o el id de una clave de la PC) y qué puede hacer."""
    id: str
    permiso: str


def clave_igual(dada: str | None, esperada: str) -> bool:
    """Compara en tiempo constante; una clave vacía nunca coincide."""
    if not dada or not esperada:
        return False
    return hmac.compare_digest(dada.encode(), esperada.encode())


def normalizar(clave: str) -> str:
    """Igual que `cassette_fm.claves.normalizar`: minúscula, sin espacios ni guiones."""
    return "".join(clave.lower().split()).replace("-", "")


def huella(clave: str) -> str:
    """Igual que `cassette_fm.claves.huella`: es lo único que el relay sabe de una clave de la PC."""
    return hashlib.sha256(normalizar(clave).encode()).hexdigest()


def validar_claves(datos: object) -> list[dict] | None:
    """La lista de claves que mandó la PC si es válida (solo `id`, `permiso` y `huella`), si no None."""
    if not isinstance(datos, list) or len(datos) > _MAX_CLAVES:
        return None
    vistos: set[str] = set()
    salida = []
    for r in datos:
        if not isinstance(r, dict):
            return None
        ident, permiso, h = r.get("id"), r.get("permiso"), r.get("huella")
        if (not isinstance(ident, str) or _ID.fullmatch(ident) is None or ident in vistos
                or permiso not in PERMISOS or not isinstance(h, str) or _HUELLA.fullmatch(h) is None):
            return None
        vistos.add(ident)
        salida.append({"id": ident, "permiso": permiso, "huella": h})
    return salida


class Acceso:
    def __init__(self, maestra: str, reloj: Callable[[], float] = time.time, max_fallos: int = 5,
                 ventana: float = 60.0, bloqueo: float = 60.0):
        self._maestra = maestra
        self._llave = hashlib.sha256(b"cassette-relay-sesion:" + maestra.encode()).digest()
        self._reloj = reloj
        self._max_fallos = max_fallos
        self._ventana = ventana
        self._bloqueo = bloqueo
        self._fallos: deque[float] = deque()
        self._bloqueado_hasta = 0.0
        self._lista: dict[str, tuple[str, str]] | None = None      # id → (permiso, huella); None = no llegó ninguna

    def poner_claves(self, claves: list[dict]) -> None:
        """La lista de la PC (ya validada con `validar_claves`): reemplaza a la anterior."""
        self._lista = {c["id"]: (c["permiso"], c["huella"]) for c in claves}

    def _firma(self, texto: str) -> str:
        return hmac.new(self._llave, texto.encode(), hashlib.sha256).hexdigest()

    def nueva_sesion(self, identidad: Identidad) -> str:
        cuerpo = f"{identidad.id}.{identidad.permiso}.{int(self._reloj()) + DURACION_SESION}"
        return f"{cuerpo}.{self._firma(cuerpo)}"

    def identidad_de_sesion(self, valor: str | None) -> Identidad | None:
        """La identidad de una cookie válida, o None. Una clave borrada deja de valer; mientras no haya llegado
        ninguna lista de la PC (el relay recién despertó) rige el permiso firmado en la cookie."""
        if not valor:
            return None
        partes = valor.split(".")
        if len(partes) != 4:
            return None
        ident, permiso, vence, firma = partes
        if (permiso not in PERMISOS or not (ident == MAESTRA or _ID.fullmatch(ident))
                or not vence.isascii() or not vence.isdigit() or len(vence) > _MAX_DIGITOS_VENCE):
            return None
        cuerpo = f"{ident}.{permiso}.{int(vence)}"
        if not hmac.compare_digest(firma.encode(), self._firma(cuerpo).encode()) or int(vence) <= self._reloj():
            return None
        if ident == MAESTRA:
            return Identidad(MAESTRA, "completa") if permiso == "completa" else None
        if self._lista is None:
            return Identidad(ident, permiso)
        vigente = self._lista.get(ident)
        return Identidad(ident, vigente[0]) if vigente is not None else None

    def probar(self, clave: str | None) -> tuple[str, Identidad | None]:
        """("ok", identidad), ("mal", None) o ("bloqueado", None). Bloqueado vale también para la clave correcta."""
        ahora = self._reloj()
        if ahora < self._bloqueado_hasta:
            return "bloqueado", None
        if clave_igual(clave, self._maestra):
            return "ok", Identidad(MAESTRA, "completa")
        if clave and self._lista:
            h = huella(clave)
            encontrada = None
            for ident, (permiso, huella_guardada) in self._lista.items():
                if hmac.compare_digest(h.encode(), huella_guardada.encode()):
                    encontrada = Identidad(ident, permiso)
            if encontrada is not None:
                return "ok", encontrada
        while self._fallos and self._fallos[0] <= ahora - self._ventana:
            self._fallos.popleft()
        self._fallos.append(ahora)
        if len(self._fallos) >= self._max_fallos:
            self._bloqueado_hasta = ahora + self._bloqueo
            self._fallos.clear()
        return "mal", None
