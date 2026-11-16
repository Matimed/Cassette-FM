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
from cassette_fm.dj.redactor_llm import (ARRANQUES, campos_de_voz, construir_peticion, limpiar_salida, marcar_nombres,
                                         corregir_momento, numeros_a_palabras, salvar,
                                         verificar)
from cassette_fm.dj.selector import elegir_ingredientes
from cassette_fm.dj.sintetizador import decir

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_log = logging.getLogger("cassette_fm")
INTENTOS = 3
_TIEMPO_MINIMO_LLM = 5.0     # si quedan menos segundos que esto, ni se le pregunta al LLM
_PALABRAS_POR_SEGUNDO = 3     # lo que dice una voz sin clips medidos: 45 palabras en un clip de 15 s
_GUIONES_PARA_RITMO = 500     # cuántos guiones viejos se miran al arrancar para medir cada voz
_RESERVA_LLM = 60.0           # lo que se le deja al LLM para escribir: hasta ahí se puede esperar a MusicBrainz


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
        self._ritmos: dict[str, float] = {}          # palabras por segundo de cada voz, medidas en sus clips
        for g in guiones.ultimos(_GUIONES_PARA_RITMO):
            self._medir(g.get("voz"), g.get("texto"), g.get("duracion"))

    def _voz_real(self, voz: str) -> str:
        """El ritmo es de la voz, no del nombre: un alias y su nombre crudo comparten lo medido."""
        return self._config.voces.get(voz, voz)

    def _medir(self, voz, texto, duracion) -> None:
        if not isinstance(voz, str) or not isinstance(texto, str) or not isinstance(duracion, (int, float)):
            return
        voz = self._voz_real(voz)
        palabras = len(texto.split())
        if palabras == 0 or duracion <= 0:
            return
        medido = palabras / duracion
        previo = self._ritmos.get(voz)
        self._ritmos[voz] = medido if previo is None else previo * 0.7 + medido * 0.3

    def _palabras_para(self, pedido: Pedido) -> int:
        """Cuántas palabras entran en la duración máxima con lo que de verdad habla esa voz (con 5 % de margen)."""
        maxima = pedido.duracion_maxima_segundos
        if not maxima:
            return self._config.palabras_maximas
        ritmo = self._ritmos.get(self._voz_real(pedido.voz))
        if ritmo is None:
            return int(maxima * _PALABRAS_POR_SEGUNDO)
        return max(15, int(maxima * ritmo * 0.95))

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
        hasta = pedido.momento.timestamp() - self._config.llm_margen_segundos - (_RESERVA_LLM if usa_llm else 0.0)
        hechos, fuentes = (self._hechos.reunir(pedido, con_wikipedia=usa_llm, hasta=hasta)
                           if self._hechos is not None else (Hechos(), None))
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
        palabras = self._palabras_para(pedido)
        disponibles = ingredientes_disponibles(pedido, hechos)
        if hechos.wikipedia is not None:
            disponibles = disponibles | {"dato"}
        # el dato (Wikipedia o MusicBrainz) va siempre que haya uno; sin ninguno el LLM no tiene qué agregar a
        # la plantilla y rellena con frases vacías o inventadas: mejor la plantilla
        if "dato" not in disponibles:
            return "sin datos del tema ni de Wikipedia para el LLM"
        con_dato = True
        elegidos = elegir_ingredientes(disponibles - {"dato"}, c.pesos_ingredientes, pedido.recientes, self._azar,
                                       max(1, c.ingredientes_max - 1) if con_dato else c.ingredientes_max,
                                       c.penalizacion_reciente)
        if con_dato:
            elegidos = (*elegidos, "dato")
        campos = campos_de_voz(pedido, hechos, self._zona)
        arranque = self._azar.choice(sorted(ARRANQUES))
        ultimo = "el LLM no dio una frase"
        limite = pedido.momento.timestamp() - c.llm_margen_segundos      # la voz arranca en `momento`
        for intento in range(1, c.llm_intentos + 1):
            restante = limite - self._reloj()
            if restante < _TIEMPO_MINIMO_LLM:
                ultimo = f"sin tiempo para el LLM (quedan {max(restante, 0):.0f} s antes de la voz)"
                break
            peticion = construir_peticion(pedido, elegidos, hechos, campos, palabras, arranque)
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
            motivo = verificar(texto, pedido, peticion, palabras, self._zona)
            if motivo is not None:
                salvado = salvar(texto, pedido, peticion, palabras, self._zona)
                if salvado is not None:
                    guion["recortado"] = motivo
                    texto, motivo = salvado, None
            marcado = None
            if motivo is None:
                try:       # primero se marcan los nombres: los números que llevan (U2, Blink-182) no se convierten
                    marcado = numeros_a_palabras(marcar_nombres(texto, pedido, hechos, self._lexico), pedido.idioma)
                    marcado = corregir_momento(marcado, pedido.momento.astimezone(self._zona), pedido.idioma)
                except ValueError as e:
                    motivo = str(e)
            if motivo is not None:
                self._guiones.anotar(**guion, texto=texto, descartado=True, motivo=motivo)
                ultimo = motivo
                continue
            prep, duracion = decir(self._sintetizador, self._fonemizar, marcado, pedido.voz, pedido.lang, ruta,
                                   velocidad=pedido.velocidad)
            self._medir(pedido.voz, prep.texto, duracion)
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
            prep, duracion = decir(self._sintetizador, self._fonemizar, redaccion.marcado, pedido.voz, pedido.lang,
                                   ruta, velocidad=pedido.velocidad)
            self._medir(pedido.voz, prep.texto, duracion)
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
