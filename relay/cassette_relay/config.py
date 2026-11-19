"""Configuración del relay: todo por variables de entorno (Render las carga como secretos)."""
from collections.abc import Mapping
from dataclasses import dataclass

CALIDADES = (64, 96, 160)      # kbps que sube la PC (protocolo del puente, versión 1)
PROTOCOLO = 1

_MIN_CLAVE = 8


class ErrorConfig(Exception):
    """Falta una variable o tiene un valor inválido. El mensaje nunca incluye el valor."""


@dataclass(frozen=True)
class Ajustes:
    ingest_token: str
    app_password: str
    puerto: int = 8080
    gracia: float = 10.0          # s que una calidad sigue pedida después de irse su último oyente
    cola_segundos: float = 15.0   # audio que se le guarda a cada oyente antes de saltar al vivo
    trabado: float = 30.0         # s que puede tardar una escritura a un oyente antes de cortarlo
    sin_audio: float = 20.0       # s sin audio para un oyente antes de cortarlo
    espera_orden: float = 10.0    # s que se espera el resultado de una orden
    vence_logo: float = 60.0      # s hasta volver a pedir un logo que no llegó
    ping: float = 20.0            # ping de los WebSockets de la PC


def desde_entorno(env: Mapping[str, str]) -> Ajustes:
    token = (env.get("INGEST_TOKEN") or "").strip()
    if not token:
        raise ErrorConfig("falta INGEST_TOKEN (la clave de la PC: la que muestra `cassette nube`)")
    clave = env.get("APP_PASSWORD") or ""
    if not clave.strip():
        raise ErrorConfig("falta APP_PASSWORD (la clave de los oyentes)")
    if len(clave) < _MIN_CLAVE:
        raise ErrorConfig(f"APP_PASSWORD tiene que tener al menos {_MIN_CLAVE} caracteres")
    crudo = (env.get("PORT") or "8080").strip()
    try:
        puerto = int(crudo)
    except ValueError:
        raise ErrorConfig("PORT tiene que ser un número de puerto") from None
    if not 0 < puerto < 65536:
        raise ErrorConfig("PORT tiene que estar entre 1 y 65535")
    return Ajustes(ingest_token=token, app_password=clave, puerto=puerto)
