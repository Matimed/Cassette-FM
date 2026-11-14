import random
import re
from zoneinfo import ZoneInfo
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ
from cassette_fm.dj.guiones import RegistroGuiones
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import Pedido
from cassette_fm.dj.plantillas import redactar
from cassette_fm.dj.texto_voz import preparar, texto_para_piper

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
INTENTOS = 3


@dataclass(frozen=True)
class Resultado:
    texto: str
    marcado: str
    ingredientes: tuple[str, ...]
    duracion: float
    audio: Path
    voz: str
    idioma: str


class Productor:
    """Encadena redactar → preparar para la voz → sintetizar → anotar el guion."""

    def __init__(self, config: ConfigServicioDJ, rutas: RutasDJ, sintetizador, fonemizar: Callable[[str, str], str],
                 lexico: Lexico, guiones: RegistroGuiones, azar: random.Random | None = None):
        self._config = config
        self._rutas = rutas
        self._sintetizador = sintetizador
        self._fonemizar = fonemizar
        self._lexico = lexico
        self._guiones = guiones
        self._azar = azar or random.Random()
        self._zona = ZoneInfo(config.zona_horaria)

    def producir(self, pedido: Pedido) -> Resultado:
        if not _ID.fullmatch(pedido.id):
            raise ValueError("el id del pedido no es válido")
        clips = self._rutas.clips
        ruta = clips / f"{pedido.id}.wav"
        if ruta.resolve().parent != clips.resolve():
            raise ValueError("el id del pedido apunta fuera del directorio de clips")
        try:
            return self._producir(pedido, ruta)
        except Exception as e:
            self._guiones.anotar(**self._base(pedido), error=str(e))
            raise

    def _base(self, pedido: Pedido) -> dict:
        return {
            "id": pedido.id, "estacion": pedido.estacion, "idioma": pedido.idioma, "voz": pedido.voz,
            "momento": pedido.momento.isoformat(),
            "anterior": asdict(pedido.anterior) if pedido.anterior else None,
            "siguiente": asdict(pedido.siguiente), "fuente": "plantilla",
        }

    def _producir(self, pedido: Pedido, ruta: Path) -> Resultado:
        maxima = pedido.duracion_maxima_segundos
        palabras = self._config.palabras_maximas
        descartadas: list[float] = []
        for _ in range(INTENTOS):
            redaccion = redactar(pedido, self._lexico, self._azar, palabras, self._zona)
            prep = preparar(redaccion.marcado, pedido.lang, self._fonemizar)
            duracion = self._sintetizador.sintetizar(prep.fonemas, pedido.voz, pedido.lang, ruta,
                                                   velocidad=pedido.velocidad, texto=texto_para_piper(prep.marcado))
            guion = dict(self._base(pedido), ingredientes=list(redaccion.ingredientes), texto=prep.texto,
                         marcado=prep.marcado, fonemas=prep.fonemas, duracion=duracion)
            if maxima is None or duracion <= maxima:
                self._guiones.anotar(**guion, audio=str(ruta))
                return Resultado(prep.texto, prep.marcado, redaccion.ingredientes, duracion, ruta,
                                 pedido.voz, pedido.idioma)
            self._guiones.anotar(**guion, descartado=True)
            ruta.unlink(missing_ok=True)
            descartadas.append(duracion)
            # la próxima vez, un texto proporcionalmente más corto
            palabras = max(5, int(len(prep.texto.split()) * maxima / duracion * 0.95))
        largos = ", ".join(f"{d:.1f}" for d in descartadas)
        raise ValueError(f"el clip dura {largos} s y el máximo es {maxima:g} s")
