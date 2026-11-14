import json
import logging
import random
import threading
import time
import wave
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from cassette_fm.agenda import transiciones
from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.cliente_dj import ClienteDJ, ErrorDJ
from cassette_fm.clips import generar_clip_de_prueba
from cassette_fm.config import ConfigDJ, Frecuencia
from cassette_fm.intervenciones import RegistroIntervenciones
from cassette_fm.planificador import Planificador

T0 = 1_800_000_000.0


def pista(n, duracion=200.0, nombre="E"):
    return Pista(Path(f"/m/{nombre}/{n:02d}.mp3"), duracion, f"Artista {n} - Tema {n}",
                 artista=f"Artista {n}", cancion=f"Tema {n}")


def estacion(nombre="E", n=12, duracion=200.0):
    return Estacion(nombre, tuple(pista(i, duracion, nombre) for i in range(n)))


class Reloj:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class ClienteFalso:
    def __init__(self):
        self.enviados, self.cancelados, self.descargados = [], [], []
        self.respuestas = {}                 # id -> dict de estado (si falta: "trabajando")
        self.error_enviar = self.error_estado = self.error_audio = None
        self.llamadas_estado = 0
        self._modo, self.error_modo = "plantillas", None

    def enviar(self, pedido):
        if self.error_enviar:
            raise self.error_enviar
        self.enviados.append(pedido)
        return pedido["id"]

    def estado(self, id):
        self.llamadas_estado += 1
        if self.error_estado:
            raise self.error_estado
        return self.respuestas.get(id, {"estado": "trabajando"})

    def descargar_audio(self, id, destino):
        if self.error_audio:
            raise self.error_audio
        self.descargados.append(id)
        return generar_clip_de_prueba(destino, 3.0)

    def cancelar(self, id):
        self.cancelados.append(id)
        return True

    def modo(self):
        if self.error_modo:
            raise self.error_modo
        return self._modo

    def poner_modo(self, modo):
        if self.error_modo:
            raise self.error_modo
        self._modo = modo
        return {"modo": modo, **({"llm": "ok"} if modo == "llm" else {})}


class LocutorFalso:
    def __init__(self, registro):
        self.registro = registro
        self.registradas, self.descartadas = [], []
        self.error = None

    def registrar(self, i):
        if self.error:
            raise self.error
        self.registro.agregar(i)
        self.registradas.append(i)

    def descartar_estacion(self, nombre):
        self.descartadas.append(nombre)
        self.registro.quitar_estacion(nombre)


CFG = ConfigDJ(margen_minutos=0.0, frecuencia=Frecuencia("temas", 1, 1), retraso_voz_segundos=1.0,
               espera_reintento_segundos=5.0, espera_reintento_maxima_segundos=40.0,
               espera_trabajo_maxima_segundos=600.0)


@pytest.fixture
def mundo(tmp_path):
    class M:
        pass

    m = M()
    m.reloj = Reloj()
    m.clips = tmp_path / "clips"
    m.clips.mkdir()
    m.archivo = tmp_path / "estado" / "planificador.json"
    m.registro = RegistroIntervenciones(tmp_path / "estado" / "i.json", m.clips, m.reloj, gracia_segundos=60.0)
    m.cliente = ClienteFalso()
    m.locutor = LocutorFalso(m.registro)
    m.cfgs = {}
    m.cfg = lambda nombre: m.cfgs.get(nombre, CFG)

    def nuevo():
        return Planificador(m.cliente, m.locutor, m.registro, m.cfg, m.archivo, m.clips, reloj=m.reloj,
                            azar=random.Random(1), gracia_segundos=60.0, intervalo_segundos=0.01)

    m.nuevo = nuevo
    m.p = nuevo()

    def listo(id_, duracion=3.0, ingredientes=("tema", "hora")):
        m.cliente.respuestas[id_] = {"estado": "listo", "duracion": duracion, "texto": "Hola.",
                                     "ingredientes": list(ingredientes), "error": None}

    m.listo = listo
    return m


def sintonizar_y_pedir(m, nombre="E"):
    est = estacion(nombre)
    m.p.al_sintonizar(est)
    m.p.paso()
    return est, m.cliente.enviados[-1]


def pasado_el_hueco(pedido):
    inicio_voz = datetime.fromisoformat(pedido["momento"]).timestamp()
    t = inicio_voz + CFG.duracion_maxima_segundos + 60.0 + 1
    assert t - T0 < CFG.espera_trabajo_maxima_segundos
    return t


def test_planifica_para_la_estacion_sintonizada_y_envia_el_pedido(mundo):
    est, pedido = sintonizar_y_pedir(mundo)
    assert pedido["estacion"] == "E" and pedido["recientes"] == []
    assert (pedido["voz"], pedido["idioma"]) == (CFG.voz, CFG.idioma)
    assert pedido["duracion_maxima_segundos"] == CFG.duracion_maxima_segundos
    destino, inicio = next(iter(transiciones(est, T0)))
    assert pedido["siguiente"]["titulo"] == destino.cancion
    assert datetime.fromisoformat(pedido["momento"]).timestamp() == pytest.approx(inicio + CFG.retraso_voz_segundos, abs=1)
    e = mundo.p.estado()
    assert e["en_curso"]["id"] == pedido["id"] and e["estacion"] == "E" and e["servicio"] == "ok"


def test_sin_estacion_sintonizada_no_planifica(mundo):
    mundo.p.paso()
    assert mundo.cliente.enviados == []


def test_con_la_radio_apagada_no_planifica_pero_lo_iniciado_termina(mundo):
    _, pedido = sintonizar_y_pedir(mundo)
    mundo.p.al_apagar()
    mundo.listo(pedido["id"])
    mundo.p.paso()
    assert [i.id for i in mundo.locutor.registradas] == [pedido["id"]]
    mundo.reloj.t += 1000
    mundo.p.paso()
    assert len(mundo.cliente.enviados) == 1


def test_no_pide_otra_si_la_estacion_ya_tiene_una_reservada(mundo):
    est = estacion()
    _, inicio = next(iter(transiciones(est, T0)))
    from cassette_fm.intervenciones import Intervencion
    audio = generar_clip_de_prueba(mundo.clips / "x.wav", 3.0)
    mundo.registro.agregar(Intervencion("previa", "E", inicio + 1, 3.0, audio, "t", str(est.pistas[0].ruta)))
    mundo.p.al_sintonizar(est)
    mundo.p.paso()
    assert mundo.cliente.enviados == []


def test_un_solo_trabajo_a_la_vez(mundo):
    est, primero = sintonizar_y_pedir(mundo)
    mundo.p.al_sintonizar(estacion("F"))
    for _ in range(3):
        mundo.p.paso()
    assert len(mundo.cliente.enviados) == 1


def test_saltar_entre_estaciones_deja_un_solo_trabajo(mundo):
    for nombre in "ABCD":
        mundo.p.al_sintonizar(estacion(nombre))
    mundo.p.paso()
    assert [p["estacion"] for p in mundo.cliente.enviados] == ["D"]
    mundo.p.al_sintonizar(estacion("A"))
    mundo.p.paso()
    assert len(mundo.cliente.enviados) == 1            # el de D sigue en curso
    mundo.listo(mundo.cliente.enviados[0]["id"])
    mundo.p.paso()
    mundo.p.paso()
    assert [p["estacion"] for p in mundo.cliente.enviados] == ["D", "A"]


def test_el_trabajo_en_curso_termina_y_se_registra_para_su_estacion(mundo):
    est, pedido = sintonizar_y_pedir(mundo, "A")
    mundo.p.al_sintonizar(estacion("B"))
    mundo.listo(pedido["id"], duracion=3.5)
    mundo.p.paso()
    (i,) = mundo.locutor.registradas
    assert i.estacion == "A" and i.id == pedido["id"] and i.duracion == 3.5 and i.texto == "Hola."
    destino, inicio = next(iter(transiciones(est, T0)))
    assert i.inicio == pytest.approx(inicio + CFG.retraso_voz_segundos) and i.pista_destino == str(destino.ruta)
    assert i.audio.parent == mundo.clips and i.audio.exists()


def test_listo_actualiza_ultima_y_recientes_y_el_proximo_pedido_los_usa(mundo):
    mundo.cfgs["E"] = replace(CFG, frecuencia=Frecuencia("temas", 3, 3))
    est, p1 = sintonizar_y_pedir(mundo)
    mundo.listo(p1["id"], ingredientes=("hora", "cancion"))
    mundo.p.paso()
    i = mundo.locutor.registradas[0]
    mundo.reloj.t = i.inicio + 20                       # terminó la voz
    mundo.p.paso()
    p2 = mundo.cliente.enviados[1]
    assert p2["recientes"] == ["hora", "cancion"]
    inicio1 = i.inicio - CFG.retraso_voz_segundos
    serie = [t for _, t in zip(range(40), (t for _, t in transiciones(est, inicio1 - 0.001)))]
    (_, inicio2) = [(None, datetime.fromisoformat(p2["momento"]).timestamp() - CFG.retraso_voz_segundos)][0]
    assert min(abs(inicio2 - t) for t in serie) < 1.5 and serie.index(min(serie, key=lambda t: abs(t - inicio2))) == 3


def test_recientes_se_recortan_a_la_cantidad_configurada(mundo):
    mundo.cfgs["E"] = replace(CFG, recientes_cantidad=2)
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.listo(p1["id"], ingredientes=("a", "b", "c"))
    mundo.p.paso()
    assert json.loads(mundo.archivo.read_text())["recientes"]["E"] == ["b", "c"]


def test_si_registrar_falla_se_borra_el_clip(mundo, caplog):
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.locutor.error = ValueError("se superpone")
    mundo.listo(p1["id"])
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        mundo.p.paso()
    assert not (mundo.clips / f"{p1['id']}.wav").exists()
    assert "se superpone" in caplog.text
    assert mundo.p.estado()["en_curso"] is None
    assert json.loads(mundo.archivo.read_text())["ultima"] == {}


def test_error_del_servicio_en_el_trabajo_espera_antes_de_reintentar(mundo, caplog):
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.cliente.respuestas[p1["id"]] = {"estado": "error", "error": "Kokoro explotó"}
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        mundo.p.paso()
    assert "Kokoro explotó" in caplog.text
    assert mundo.p.estado()["en_curso"] is None
    mundo.reloj.t += 4
    mundo.p.paso()
    assert len(mundo.cliente.enviados) == 1             # todavía dentro de la espera (5 s)
    mundo.reloj.t += 2
    mundo.p.paso()
    assert len(mundo.cliente.enviados) == 2
    mundo.cliente.respuestas[mundo.cliente.enviados[1]["id"]] = {"estado": "error", "error": "otra vez"}
    mundo.p.paso()
    mundo.reloj.t += 6
    mundo.p.paso()
    assert len(mundo.cliente.enviados) == 2             # la espera creció a 10 s
    mundo.reloj.t += 5
    mundo.p.paso()
    assert len(mundo.cliente.enviados) == 3


def test_servicio_caido_avisa_una_sola_vez_y_se_recupera(mundo, caplog):
    mundo.p.al_sintonizar(estacion())
    mundo.cliente.error_enviar = ErrorDJ("el servicio DJ no responde en http://x")
    esperas = []
    with caplog.at_level(logging.INFO, logger="cassette_fm"):
        for _ in range(5):
            mundo.p.paso()
            e = mundo.p.estado()
            esperas.append(round(e["proximo_intento_en"]))
            assert e["servicio"] == "no responde" and "no responde" in e["error"]
            mundo.reloj.t += e["proximo_intento_en"] + 0.1
        avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(avisos) == 1
        assert esperas == [5, 10, 20, 40, 40]            # duplica hasta el tope
        mundo.cliente.error_enviar = None
        mundo.p.paso()
    assert mundo.p.estado()["servicio"] == "ok" and mundo.p.estado()["proximo_intento_en"] is None
    assert len(mundo.cliente.enviados) == 1
    assert any(r.levelno == logging.INFO and "volvió" in r.getMessage() for r in caplog.records)


def test_servicio_caido_con_un_trabajo_en_curso_lo_conserva(mundo):
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.cliente.error_estado = ErrorDJ("el servicio DJ no responde")
    mundo.p.paso()
    assert mundo.p.estado()["en_curso"]["id"] == p1["id"]
    mundo.cliente.error_estado = None
    mundo.reloj.t += 6
    mundo.listo(p1["id"])
    mundo.p.paso()
    assert len(mundo.locutor.registradas) == 1


def test_error_al_descargar_conserva_el_trabajo(mundo):
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.listo(p1["id"])
    mundo.cliente.error_audio = ErrorDJ("audio incompleto")
    mundo.p.paso()
    assert mundo.p.estado()["en_curso"] and mundo.locutor.registradas == []
    mundo.cliente.error_audio = None
    mundo.reloj.t += 6
    mundo.p.paso()
    assert len(mundo.locutor.registradas) == 1


def test_trabajo_demasiado_viejo_se_cancela(mundo):
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.reloj.t = pasado_el_hueco(p1)                  # pasó inicio_voz + máximo + gracia (y no el tope de espera)
    mundo.p.paso()
    assert mundo.cliente.cancelados == [p1["id"]] and mundo.p.estado()["en_curso"] is None


def test_trabajo_que_tarda_demasiado_se_cancela(mundo):
    mundo.cfgs["E"] = replace(CFG, espera_trabajo_maxima_segundos=30.0)
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.reloj.t += 31
    mundo.p.paso()
    assert mundo.cliente.cancelados == [p1["id"]] and mundo.p.estado()["en_curso"] is None


def test_el_servicio_olvida_el_trabajo_se_limpia(mundo):
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.cliente.respuestas[p1["id"]] = None
    mundo.p.paso()
    assert mundo.p.estado()["en_curso"] is None


def test_se_retoma_un_trabajo_en_curso_tras_reiniciar(mundo):
    est, p1 = sintonizar_y_pedir(mundo)
    otro = mundo.nuevo()
    otro.al_sintonizar(est)                              # la misma agenda: no descarta nada
    assert otro.estado()["en_curso"]["id"] == p1["id"]
    mundo.listo(p1["id"])
    otro.paso()
    assert [i.id for i in mundo.locutor.registradas] == [p1["id"]]
    assert mundo.locutor.descartadas == []


def test_un_trabajo_ya_registrado_no_borra_su_clip_al_retomarse(mundo):
    est, p1 = sintonizar_y_pedir(mundo)
    mundo.listo(p1["id"])
    mundo.p.paso()
    clip = mundo.clips / f"{p1['id']}.wav"
    assert clip.exists()
    # la radio se cayó antes de guardar que el trabajo terminó: el archivo todavía lo trae como en curso
    estado = json.loads(mundo.archivo.read_text())
    estado["en_curso"] = {"id": p1["id"], "estacion": "E", "inicio_tema": T0, "inicio_voz": T0 + 1,
                          "pista_destino": "/m/E/00.mp3", "enviado_en": T0, "duracion_maxima": 15.0}
    mundo.archivo.write_text(json.dumps(estado))
    otro = mundo.nuevo()
    otro.paso()
    assert clip.exists() and otro.estado()["en_curso"] is None and len(mundo.locutor.registradas) == 1


def test_se_descarta_un_trabajo_guardado_cuyo_hueco_ya_paso(mundo):
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.reloj.t = pasado_el_hueco(p1)
    otro = mundo.nuevo()
    otro.paso()
    assert otro.estado()["en_curso"] is None and mundo.cliente.cancelados == [p1["id"]]


@pytest.mark.parametrize("contenido", [None, "{no es json", "[1, 2]", '{"en_curso": {"id": "../x"}}',
                                       '{"ultima": {"E": "mal"}}', '{"en_curso": {"id": "a"}}'])
def test_archivo_corrupto_o_ausente_arranca_vacio(mundo, contenido):
    if contenido is not None:
        mundo.archivo.parent.mkdir(parents=True, exist_ok=True)
        mundo.archivo.write_text(contenido)
    p = mundo.nuevo()
    assert p.estado()["en_curso"] is None
    p.al_sintonizar(estacion())
    p.paso()
    assert len(mundo.cliente.enviados) == 1


def test_rescan_que_cambia_la_agenda_descarta_reservas_y_trabajo(mundo):
    est, p1 = sintonizar_y_pedir(mundo)
    otra_agenda = Estacion("E", est.pistas[:-1])
    mundo.p.al_rescan([otra_agenda, estacion("Z")])
    assert mundo.locutor.descartadas == ["E"]
    assert mundo.p.estado()["en_curso"] is None and mundo.p.estado()["estacion"] == "E"
    mundo.p.paso()
    assert mundo.cliente.cancelados == [p1["id"]]
    assert len(mundo.cliente.enviados) == 2              # y pide de nuevo con la agenda nueva


def test_rescan_sin_cambios_no_toca_nada(mundo):
    est, p1 = sintonizar_y_pedir(mundo)
    mundo.p.al_rescan([estacion("E")])
    assert mundo.locutor.descartadas == [] and mundo.p.estado()["en_curso"]["id"] == p1["id"]


def test_rescan_en_que_desaparece_la_sintonizada_es_como_apagar(mundo):
    sintonizar_y_pedir(mundo)
    mundo.p.al_rescan([estacion("Z")])
    assert mundo.p.estado()["estacion"] is None


def test_pedir_ahora_ignora_la_frecuencia_y_usa_el_margen_dado(mundo):
    mundo.cfgs["E"] = replace(CFG, frecuencia=Frecuencia("temas", 9, 9), margen_minutos=30.0)
    est = estacion()
    mundo.p.al_sintonizar(est)
    r = mundo.p.pedir_ahora(30)
    assert r["estacion"] == "E" and r["id"] == mundo.cliente.enviados[0]["id"] and "Tema" in r["tema"]
    assert 30 <= r["en_segundos"] <= 30 + 200 + 2
    assert r["inicio"] == pytest.approx(T0 + r["en_segundos"])
    assert mundo.p.estado()["en_curso"]["id"] == r["id"]


def test_pedir_ahora_falla_sin_estacion_o_con_trabajo_en_curso_o_sin_hueco(mundo):
    with pytest.raises(ValueError, match="estación"):
        mundo.p.pedir_ahora(20)
    mundo.p.al_sintonizar(Estacion("X", (Pista(Path("/m/x.mp3"), 100.0, "x"),)))
    with pytest.raises(ValueError, match="artista"):
        mundo.p.pedir_ahora(20)
    mundo.p.al_sintonizar(estacion())
    mundo.p.pedir_ahora(20)
    with pytest.raises(ValueError, match="en curso"):
        mundo.p.pedir_ahora(20)


def test_pedir_ahora_con_el_servicio_caido_da_ValueError_con_el_mensaje(mundo):
    mundo.p.al_sintonizar(estacion())
    mundo.cliente.error_enviar = ErrorDJ("el servicio DJ no responde en http://x")
    with pytest.raises(ValueError, match="no responde"):
        mundo.p.pedir_ahora(20)
    assert mundo.p.estado()["en_curso"] is None


def test_la_configuracion_por_estacion_manda(mundo):
    mundo.cfgs["B"] = replace(CFG, voz="am_michael", idioma="en", personalidad="irónico")
    mundo.p.al_sintonizar(estacion("B"))
    mundo.p.paso()
    p = mundo.cliente.enviados[0]
    assert (p["voz"], p["idioma"], p["personalidad"]) == ("am_michael", "en", "irónico")


def test_los_hooks_no_esperan_a_la_red(mundo):
    liberar = threading.Event()
    original = mundo.cliente.enviar

    def lento(pedido):
        liberar.wait(5)
        return original(pedido)

    mundo.cliente.enviar = lento
    mundo.p.al_sintonizar(estacion())
    hilo = threading.Thread(target=mundo.p.paso, daemon=True)
    hilo.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    mundo.p.al_sintonizar(estacion("F"))
    mundo.p.al_apagar()
    mundo.p.estado()
    assert time.monotonic() - t0 < 0.5
    liberar.set()
    hilo.join(2)


def test_el_hilo_arranca_y_se_detiene_sin_dejar_hilos(mundo):
    antes = {t.name for t in threading.enumerate()}
    mundo.p.al_sintonizar(estacion())
    mundo.p.iniciar()
    fin = time.monotonic() + 3
    while not mundo.cliente.enviados and time.monotonic() < fin:
        time.sleep(0.01)
    assert len(mundo.cliente.enviados) == 1
    mundo.p.cerrar()
    assert mundo.cliente.cancelados == []                # cerrar no cancela el trabajo en curso
    assert json.loads(mundo.archivo.read_text())["en_curso"]["id"] == mundo.cliente.enviados[0]["id"]
    assert {t.name for t in threading.enumerate()} == antes


def test_integracion_con_el_servicio_dj_real(tmp_path, servicio_dj):
    servicio = servicio_dj(duracion=3.0)
    cliente = ClienteDJ(servicio.url, timeout=5)
    clips = tmp_path / "clips"
    clips.mkdir()
    registro = RegistroIntervenciones(tmp_path / "i.json", clips, time.time, gracia_segundos=60.0)
    locutor = LocutorFalso(registro)
    cfg = replace(CFG, retraso_voz_segundos=0.1)
    p = Planificador(cliente, locutor, registro, lambda n: cfg, tmp_path / "plan.json", clips,
                     azar=random.Random(1))
    est = Estacion("Rock", tuple(pista(i, 3.0, "Rock") for i in range(6)))
    p.al_sintonizar(est)
    fin = time.monotonic() + 15
    while not locutor.registradas and time.monotonic() < fin:
        p.paso()
        time.sleep(0.05)
    assert len(locutor.registradas) == 1
    i = locutor.registradas[0]
    with wave.open(str(i.audio)) as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(3.0, abs=0.01)
    assert i.texto and i.estacion == "Rock"
    (guion,) = servicio.guiones.ultimos(5)
    assert guion["id"] == i.id and guion["fuente"] == "plantilla"


# --- revisión final ---

def test_un_rescan_durante_la_consulta_no_deja_registrar_el_hueco_viejo(mundo):
    est, p1 = sintonizar_y_pedir(mundo)
    mundo.listo(p1["id"])
    original = mundo.cliente.estado

    def estado_y_rescan(id_):
        r = original(id_)
        mundo.p.al_rescan([Estacion("E", est.pistas[:-1])])      # llega mientras se esperaba al servicio
        return r

    mundo.cliente.estado = estado_y_rescan
    mundo.p.paso()
    assert mundo.locutor.registradas == [] and mundo.registro.todas() == []
    assert not (mundo.clips / f"{p1['id']}.wav").exists()
    assert json.loads(mundo.archivo.read_text())["ultima"] == {}


def test_un_rescan_durante_el_POST_cancela_el_pedido_viejo(mundo):
    est = estacion()
    mundo.p.al_sintonizar(est)
    original = mundo.cliente.enviar

    def enviar_y_rescan(pedido):
        r = original(pedido)
        mundo.p.al_rescan([Estacion("E", est.pistas[:-1])])
        return r

    mundo.cliente.enviar = enviar_y_rescan
    mundo.p.paso()
    id_viejo = mundo.cliente.enviados[0]["id"]
    assert mundo.p.estado()["en_curso"] is None
    mundo.p.paso()
    assert id_viejo in mundo.cliente.cancelados


@pytest.mark.parametrize("respuesta", [None, {"estado": "cancelado"}])
def test_si_el_servicio_olvida_o_cancela_no_se_vuelve_a_pedir_enseguida(mundo, respuesta):
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.cliente.respuestas[p1["id"]] = respuesta
    mundo.p.paso()
    for _ in range(3):
        mundo.p.paso()
    assert len(mundo.cliente.enviados) == 1
    mundo.reloj.t += 6
    mundo.p.paso()
    assert len(mundo.cliente.enviados) == 2


def test_un_id_distinto_del_pedido_se_trata_como_fallo(mundo):
    mundo.p.al_sintonizar(estacion())
    mundo.cliente.enviar = lambda pedido: "otro-id"
    mundo.p.paso()
    assert mundo.p.estado()["en_curso"] is None and mundo.p.estado()["servicio"] == "no responde"


def test_pedir_ahora_despues_de_una_caida_no_hereda_la_espera(mundo):
    mundo.p.al_sintonizar(estacion())
    mundo.cliente.error_enviar = ErrorDJ("no responde")
    for _ in range(4):
        mundo.p.paso()
        mundo.reloj.t += mundo.p.estado()["proximo_intento_en"] + 0.1
    mundo.cliente.error_enviar = None
    r = mundo.p.pedir_ahora(20)
    mundo.listo(r["id"])
    mundo.p.paso()
    assert [i.id for i in mundo.locutor.registradas] == [r["id"]]


@pytest.mark.parametrize("duracion", [float("nan"), -1.0, 0.0, True, float("inf"), 999.0, "3"])
def test_una_duracion_invalida_del_servicio_se_rechaza(mundo, duracion):
    _, p1 = sintonizar_y_pedir(mundo)
    mundo.listo(p1["id"], duracion=duracion)
    mundo.p.paso()
    assert mundo.locutor.registradas == [] and not (mundo.clips / f"{p1['id']}.wav").exists()
    assert mundo.p.estado()["en_curso"] is None


def test_al_sintonizar_con_otra_agenda_descarta_lo_reservado(mundo):
    est, p1 = sintonizar_y_pedir(mundo)
    mundo.listo(p1["id"])
    mundo.p.paso()
    assert mundo.registro.de_la_estacion("E")
    mundo.p.al_apagar()
    otra = mundo.nuevo()                                   # reinicio con la biblioteca cambiada
    otra.al_sintonizar(Estacion("E", est.pistas[:-1]))
    assert mundo.locutor.descartadas == ["E"]
    assert json.loads(mundo.archivo.read_text())["ultima"] == {}


def test_si_desaparece_una_estacion_en_el_rescan_se_descartan_sus_reservas(mundo):
    sintonizar_y_pedir(mundo, "E")
    mundo.p.al_sintonizar(estacion("F"))
    mundo.p.al_rescan([estacion("F")])
    assert mundo.locutor.descartadas == ["E"]


def test_una_ultima_muy_vieja_no_deja_a_la_estacion_sin_DJ(mundo):
    from cassette_fm.planificacion import Ultima
    mundo.p._ultima["E"] = Ultima(T0 - 400 * 86400, T0 - 400 * 86400 + 10)
    mundo.p.al_sintonizar(estacion())
    t0 = time.monotonic()
    mundo.p.paso()
    assert len(mundo.cliente.enviados) == 1 and time.monotonic() - t0 < 1.0


def test_modo_delega_en_el_cliente_y_convierte_errores(mundo):
    assert mundo.p.modo() == {"modo": "plantillas"}
    assert mundo.p.modo("llm") == {"modo": "llm", "llm": "ok"} and mundo.p.modo() == {"modo": "llm"}
    mundo.cliente.error_modo = ErrorDJ("el servicio DJ no responde en http://x")
    with pytest.raises(ValueError, match="no responde"):
        mundo.p.modo()
    with pytest.raises(ValueError, match="no responde"):
        mundo.p.modo("plantillas")
