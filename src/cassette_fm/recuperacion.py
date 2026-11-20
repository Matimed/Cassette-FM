"""Último recurso cuando una emisora de Spotify no logra sonar: reiniciar el servicio y retomar donde estaba.

Antes se apagaba la radio, y apagada no se la puede prender desde afuera (la nube no prende ni apaga). Reiniciar el servicio
(que reinicia también a Soloist, donde suele estar lo trabado) es lo que se haría a mano. Un marcador en disco hace dos cosas:
le dice al servicio que arranca qué emisora retomar, y frena los reinicios en cadena (no se reinicia dos veces en
`VENTANA_SEGUNDOS`: si el reinicio no arregló nada, ahí sí se apaga)."""
import json
import logging
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

_log = logging.getLogger("cassette_fm")

VENTANA_SEGUNDOS = 600          # entre un reinicio y el siguiente
VIGENCIA_SEGUNDOS = 300         # un marcador más viejo que esto no es de este arranque: no se retoma
ESPERA_SOLOIST_SEGUNDOS = 90    # lo que se espera a que Soloist vuelva a conectarse antes de retomar la emisora
UNIDAD = "cassette-fm.service"


def _bajo_systemd() -> bool:
    return bool(os.environ.get("INVOCATION_ID"))           # systemd se lo pone a los procesos de sus unidades


def _reiniciar_con_systemd() -> None:
    # --no-block: encola el reinicio y vuelve (el servicio se detiene en medio de este mismo pedido)
    subprocess.Popen(["systemctl", "--user", "--no-block", "restart", UNIDAD], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def merece_reinicio(estacion, motivo: str | None) -> bool:
    """¿Un reinicio puede arreglar este fallo? Lo que se traba es Spotify/Soloist; una carpeta sin temas, o Spotify abierto
    en otro dispositivo, siguen igual después de reiniciar."""
    return estacion.fuente == "spotify" and "otro dispositivo" not in (motivo or "")


def _leer(ruta: Path) -> dict | None:
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("cuando"), (int, float)) or isinstance(datos["cuando"], bool):
        return None
    return datos


def _escribir(ruta: Path, datos: dict) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ruta)


def pedir_reinicio(ruta: Path, estacion: str, motivo: str | None, ahora: Callable[[], float] = time.time,
                   bajo_systemd: Callable[[], bool] = _bajo_systemd,
                   reiniciar: Callable[[], None] = _reiniciar_con_systemd) -> bool:
    """Pide reiniciar el servicio. False si no se puede o no corresponde (ya se reinició hace poco, o no corre bajo systemd):
    quien llama sigue con su plan B (apagar)."""
    previo = _leer(ruta)
    if previo is not None and ahora() - previo["cuando"] < VENTANA_SEGUNDOS:
        _log.warning("la emisora %r sigue sin sonar y ya se reinició hace menos de %d min: no se reinicia de nuevo",
                     estacion, VENTANA_SEGUNDOS // 60)
        return False
    if not bajo_systemd():
        return False
    _escribir(ruta, {"cuando": ahora(), "estacion": estacion, "motivo": motivo, "retomado": False})
    try:
        reiniciar()
    except OSError as e:
        _log.warning("no se pudo pedir el reinicio del servicio: %s", e)
        Path(ruta).unlink(missing_ok=True)
        return False
    _log.warning("la emisora %r no logra sonar (%s): se reinicia el servicio", estacion, motivo)
    return True


def a_retomar(ruta: Path, ahora: Callable[[], float] = time.time) -> str | None:
    """La emisora que sonaba cuando se pidió el reinicio, si este arranque es el de ese reinicio y no se retomó todavía."""
    datos = _leer(ruta)
    if datos is None or datos.get("retomado") or ahora() - datos["cuando"] > VIGENCIA_SEGUNDOS:
        return None
    estacion = datos.get("estacion")
    return estacion if isinstance(estacion, str) and estacion else None


def marcar_retomado(ruta: Path) -> None:
    """Se queda el marcador (es el freno de los reinicios), pero ya no se vuelve a retomar."""
    datos = _leer(ruta)
    if datos is not None:
        _escribir(ruta, {**datos, "retomado": True})


def retomar(ruta: Path, radio, listo: Callable[[], bool], ahora: Callable[[], float] = time.time,
            dormir: Callable[[float], None] = time.sleep, espera: float = ESPERA_SOLOIST_SEGUNDOS) -> bool:
    """Prende la radio en la emisora que sonaba, cuando `listo()` (Soloist conectado) o, si no llega, pasada la `espera`.
    El monitor local y el volumen quedan como estaban. Si falla otra vez, la radio sabe qué hacer (otra emisora, o apagarse)."""
    nombre = a_retomar(ruta, ahora)
    if nombre is None:
        return False
    marcar_retomado(ruta)                     # antes de intentar: si algo se cuelga no se reintenta en cada arranque
    limite = ahora() + espera
    while not listo() and ahora() < limite:
        dormir(1.0)
    _log.info("tras el reinicio se retoma la emisora %r", nombre)
    radio.sintonizar(nombre, oir_aca=False)
    return True
