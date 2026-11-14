import logging
import random
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ
from cassette_fm.dj.hechos import FuenteHechos, Hechos
from cassette_fm.dj.llm import ClienteLLM, ErrorLLM
from cassette_fm.dj.modo import ModoDJ
from cassette_fm.dj.guiones import RegistroGuiones
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import Pedido
from cassette_fm.dj.plantillas import ingredientes_disponibles, redactar
from cassette_fm.dj.redactor_llm import (campos_de_voz, construir_peticion, limpiar_salida, marcar_nombres,
                                         numeros_a_palabras, verificar)
from cassette_fm.dj.selector import elegir_ingredientes
from cassette_fm.dj.texto_voz import preparar, texto_para_piper

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_log = logging.getLogger("cassette_fm")
INTENTOS = 3
_TIEMPO_MINIMO_LLM = 5.0     # si quedan menos segundos que esto, ni se le pregunta al LLM


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
                 lexico: Lexico, guiones: RegistroGuiones, azar: random.Random | None = None,
                 hechos: FuenteHechos | None = None, modo: ModoDJ | None = None, llm: ClienteLLM | None = None,
                 reloj: Callable[[], float] = time.time):
        self._config = config
        self._rutas = rutas
        self._sintetizador = sintetizador
        self._fonemizar = fonemizar
        self._lexico = lexico
        self._guiones = guiones
        self._azar = azar or random.Random()
        self._hechos = hechos
        self._modo = modo
        self._llm = llm
        self._llm_avisado = False
        self._reloj = reloj
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
        modo = self._modo.actual() if self._modo is not None else "plantillas"      # una sola vez por pedido
        motivo = None
        usa_llm = modo == "llm" and self._llm is not None
        if modo == "llm" and self._llm is None:
            motivo = "el modo llm está activo pero no hay cliente de LLM"
        hechos, fuentes = (self._hechos.reunir(pedido, con_wikipedia=usa_llm) if self._hechos is not None
                           else (Hechos(), None))
        if usa_llm:
            resultado = self._producir_llm(pedido, ruta, hechos, fuentes)
            if isinstance(resultado, Resultado):
                return resultado
            motivo = resultado
        return self._producir_plantillas(pedido, ruta, hechos, fuentes, motivo)

    def _producir_llm(self, pedido: Pedido, ruta: Path, hechos: Hechos, fuentes) -> Resultado | str:
        """Intenta con el LLM; devuelve el Resultado o el motivo por el que hay que usar plantillas."""
        c = self._config
        maxima = pedido.duracion_maxima_segundos
        palabras = c.palabras_maximas
        disponibles = ingredientes_disponibles(pedido, hechos)
        if hechos.wikipedia is not None:
            disponibles = disponibles | {"dato"}
        elegidos = elegir_ingredientes(disponibles, c.pesos_ingredientes, pedido.recientes, self._azar,
                                       c.ingredientes_max, c.penalizacion_reciente)
        campos = campos_de_voz(pedido, hechos, self._zona)
        ultimo = "el LLM no dio una frase"
        limite = pedido.momento.timestamp() - c.llm_margen_segundos      # la voz arranca en `momento`
        for intento in range(1, c.llm_intentos + 1):
            restante = limite - self._reloj()
            if restante < _TIEMPO_MINIMO_LLM:
                ultimo = f"sin tiempo para el LLM (quedan {max(restante, 0):.0f} s antes de la voz)"
                break
            peticion = construir_peticion(pedido, elegidos, hechos, campos, palabras)
            guion = dict(self._base(pedido), fuente="llm", ingredientes=list(elegidos), modelo=c.llm_modelo,
                         intento=intento, sistema=peticion.sistema, usuario=peticion.usuario)
            if fuentes is not None:
                guion["hechos"] = fuentes
            try:
                crudo = self._llm.generar(peticion.sistema, peticion.usuario, timeout=min(c.llm_timeout_segundos, restante))
            except ErrorLLM as e:
                if not self._llm_avisado:
                    self._llm_avisado = True
                    _log.warning("%s: las frases salen por plantillas hasta que vuelva", e)
                self._guiones.anotar(**guion, crudo=None, descartado=True, motivo=str(e))
                return str(e)                          # sin servidor no tiene sentido reintentar
            self._llm_avisado = False
            guion["crudo"] = crudo
            texto = limpiar_salida(crudo)
            motivo = verificar(texto, pedido, peticion, palabras)
            marcado = None
            if motivo is None:
                try:       # primero se marcan los nombres: los números que llevan (U2, Blink-182) no se convierten
                    marcado = numeros_a_palabras(marcar_nombres(texto, pedido, hechos, self._lexico), pedido.idioma)
                except ValueError as e:
                    motivo = str(e)
            if motivo is not None:
                self._guiones.anotar(**guion, texto=texto, descartado=True, motivo=motivo)
                ultimo = motivo
                continue
            prep = preparar(marcado, pedido.lang, self._fonemizar)
            duracion = self._sintetizador.sintetizar(prep.fonemas, pedido.voz, pedido.lang, ruta,
                                                   velocidad=pedido.velocidad, texto=texto_para_piper(prep.marcado))
            guion.update(texto=prep.texto, marcado=prep.marcado, fonemas=prep.fonemas, duracion=duracion)
            if maxima is None or duracion <= maxima:
                self._guiones.anotar(**guion, audio=str(ruta))
                return Resultado(prep.texto, prep.marcado, tuple(elegidos), duracion, ruta, pedido.voz, pedido.idioma)
            ruta.unlink(missing_ok=True)
            ultimo = f"el clip dura {duracion:.1f} s y el máximo es {maxima:g} s"
            self._guiones.anotar(**guion, descartado=True, motivo=ultimo)
            palabras = max(8, int(len(prep.texto.split()) * maxima / duracion * 0.95))
        return ultimo

    def _producir_plantillas(self, pedido: Pedido, ruta: Path, hechos: Hechos, fuentes,
                             motivo: str | None) -> Resultado:
        maxima = pedido.duracion_maxima_segundos
        palabras = self._config.palabras_maximas
        descartadas: list[float] = []
        c = self._config
        for _ in range(INTENTOS):
            redaccion = redactar(pedido, self._lexico, self._azar, palabras, self._zona, hechos=hechos,
                                 pesos=c.pesos_ingredientes, maximo=c.ingredientes_max,
                                 penalizacion=c.penalizacion_reciente)
            prep = preparar(redaccion.marcado, pedido.lang, self._fonemizar)
            duracion = self._sintetizador.sintetizar(prep.fonemas, pedido.voz, pedido.lang, ruta,
                                                   velocidad=pedido.velocidad, texto=texto_para_piper(prep.marcado))
            guion = dict(self._base(pedido), ingredientes=list(redaccion.ingredientes), texto=prep.texto,
                         marcado=prep.marcado, fonemas=prep.fonemas, duracion=duracion)
            if fuentes is not None:
                guion["hechos"] = fuentes
            if motivo is not None:
                guion["motivo"] = motivo
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
