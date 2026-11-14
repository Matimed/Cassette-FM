import json
import math
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.hechos.cache import CacheHechos

_log = logging.getLogger("cassette_fm")


@dataclass(frozen=True)
class Clima:
    temperatura: int        # °C redondeados
    cielo: str              # despejado | nublado | lluvia | tormenta | niebla | nieve
    es_de_dia: bool


def _cielo(codigo: int) -> str | None:
    """Códigos WMO de open-meteo."""
    if codigo in (0, 1):
        return "despejado"
    if codigo in (2, 3):
        return "nublado"
    if codigo in (45, 48):
        return "niebla"
    if 51 <= codigo <= 67 or 80 <= codigo <= 82:
        return "lluvia"
    if 71 <= codigo <= 77 or codigo in (85, 86):
        return "nieve"
    if 95 <= codigo <= 99:
        return "tormenta"
    return None


class _Fallo(Exception):
    pass


class ClienteClima:
    """Clima actual de open-meteo (sin clave). Nunca lanza: sin dato devuelve None."""

    def __init__(self, config: ConfigServicioDJ, cache: CacheHechos, reloj: Callable[[], float] = time.time):
        self._config = config
        self._cache = cache
        self._avisado = False

    def actual(self) -> Clima | None:
        fallo: list[Exception] = []

        buscado = []

        def buscar():
            try:
                valor = self._pedir()
                buscado.append(1)
                return valor
            except _Fallo as e:
                fallo.append(e)
                return None

        c = self._config

        def vigencia(valor) -> float:
            return c.cache_error_minutos * 60 if fallo else c.cache_clima_minutos * 60

        valor = self._cache.consultar("clima", vigencia, buscar)
        if fallo:
            if not self._avisado:
                self._avisado = True
                _log.warning("no se pudo obtener el clima (%s): las frases siguen sin clima", fallo[0])
            return None
        if buscado:
            self._avisado = False        # una consulta de verdad salió bien (no una respuesta de la caché)
        if not isinstance(valor, dict):
            return None
        try:
            return Clima(int(valor["temperatura"]), str(valor["cielo"]), bool(valor["es_de_dia"]))
        except (KeyError, TypeError, ValueError):
            return None

    def _pedir(self) -> dict:
        c = self._config
        consulta = urllib.parse.urlencode({
            "latitude": c.latitud, "longitude": c.longitud, "current": "temperature_2m,weather_code,is_day",
            "timezone": c.zona_horaria})
        url = f"{c.open_meteo_url}?{consulta}"
        try:
            with urllib.request.urlopen(url, timeout=c.timeout_hechos_segundos) as r:
                datos = json.loads(r.read().decode("utf-8"))
        except Exception as e:             # red, HTTP, timeout, JSON: todo es "sin dato"
            raise _Fallo(f"open-meteo: {type(e).__name__}: {e}") from None
        actual = datos.get("current") if isinstance(datos, dict) else None
        if not isinstance(actual, dict):
            raise _Fallo("open-meteo: la respuesta no trae 'current'")
        temp, codigo, dia = actual.get("temperature_2m"), actual.get("weather_code"), actual.get("is_day")
        if (isinstance(temp, bool) or not isinstance(temp, (int, float)) or isinstance(codigo, bool)
                or not isinstance(codigo, int) or dia not in (0, 1) or isinstance(dia, bool)):
            raise _Fallo("open-meteo: los campos de 'current' no son los esperados")
        if not math.isfinite(temp) or not -99 <= round(temp) <= 99:
            raise _Fallo(f"open-meteo: temperatura absurda ({temp})")
        cielo = _cielo(codigo)
        if cielo is None:
            raise _Fallo(f"open-meteo: código de clima desconocido ({codigo})")
        return {"temperatura": round(temp), "cielo": cielo, "es_de_dia": bool(dia)}
