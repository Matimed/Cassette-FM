import itertools
import logging
import time
from pathlib import Path

import pytest

from cassette_fm.biblioteca import Pista
from cassette_fm.config import ConfigDJ
from cassette_fm.intervenciones import Intervencion, RegistroIntervenciones
from cassette_fm.locutor import Locutor
from cassette_fm.mpv import ClienteMpv, ErrorMpv

T0 = 10_000.0
CFG = ConfigDJ(retraso_voz_segundos=0.05, rampa_bajada_segundos=0.01, rampa_subida_segundos=0.01)


class Reloj:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class MusicaFalsa:
    def __init__(self):
        self.llamadas = []

    def atenuar(self, factor, segundos):
        self.llamadas.append((factor, segundos))


class VozFalsa:
    def __init__(self):
        self.comandos = []
        self.al_evento = None
        self.error = False
        self.cerrada = False
        self._ids = itertools.count(1)
        self.ultimo_id = None

    def comando(self, *args, **kw):
        self.comandos.append((args, kw))
        if args[0] == "loadfile":
            if self.error:
                raise ErrorMpv("no se pudo cargar")
            self.ultimo_id = next(self._ids)
            return {"playlist_entry_id": self.ultimo_id}
        return None

    def fin(self, id_=None):
        self.al_evento({"event": "end-file", "reason": "eof",
                        "playlist_entry_id": self.ultimo_id if id_ is None else id_})

    def cerrar(self):
        self.cerrada = True

    def cargas(self):
        return [c for c in self.comandos if c[0][0] == "loadfile"]


@pytest.fixture
def mundo(tmp_path, crear_wav):
    reloj = Reloj()
    clips = tmp_path / "clips"
    clips.mkdir()
    registro = RegistroIntervenciones(tmp_path / "i.json", clips, reloj, gracia_segundos=60.0)
    voz, musica = VozFalsa(), MusicaFalsa()
    cuenta = itertools.count()

    class M:
        pass

    m = M()
    m.reloj, m.registro, m.voz, m.musica = reloj, registro, voz, musica
    m.cfg = CFG
    m.locutor = Locutor(voz, musica, registro, lambda n: m.cfg, reloj)

    def iv(inicio, dur=10.0, estacion="E", destino="/m/t.mp3"):
        n = next(cuenta)
        audio = crear_wav(clips / f"c{n}.wav", dur)
        return Intervencion(f"i{n}", estacion, inicio, dur, audio, "texto", destino)

    m.iv = iv
    return m


def esperar(cond, timeout=1.5):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(0.01)
    return False


def start_de(carga):
    return float(carga[1]["options"]["start"])


def test_registrar_con_la_ventana_activa_habla_desde_el_segundo_que_corresponde(mundo):
    mundo.locutor.al_sintonizar("E")
    i = mundo.iv(T0 - 3)
    mundo.locutor.registrar(i)
    cargas = mundo.voz.cargas()
    assert len(cargas) == 1 and cargas[0][1]["url"] == str(i.audio)
    assert start_de(cargas[0]) == pytest.approx(3.0)
    assert mundo.musica.llamadas[0] == (CFG.nivel_musica_con_voz, 0.01)
    assert mundo.locutor.hablando


def test_no_habla_si_quedan_menos_del_minimo(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 9))          # dura 10: quedan 1,0 < 1,5
    assert mundo.voz.cargas() == [] and mundo.musica.llamadas == []


def test_ventana_futura_o_pasada_no_habla(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 + 30))
    mundo.locutor.registrar(mundo.iv(T0 - 50))
    assert mundo.voz.cargas() == []


def test_registrar_rechaza_un_clip_demasiado_largo(mundo):
    with pytest.raises(ValueError):
        mundo.locutor.registrar(mundo.iv(T0 + 30, dur=20.0))
    assert mundo.registro.todas() == []


def test_la_voz_se_ancla_al_inicio_real_del_tema(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 + 20))
    mundo.locutor.pista_iniciada(Pista(Path("/m/t.mp3"), 200.0, "t"), "E")
    assert esperar(lambda: mundo.voz.cargas())
    assert start_de(mundo.voz.cargas()[0]) == pytest.approx(0.0)


@pytest.mark.parametrize("ruta,estacion,inicio", [
    ("/m/otro.mp3", "E", T0 + 20),       # otro tema
    ("/m/t.mp3", "OTRA", T0 + 20),       # estación que no es la sintonizada
    ("/m/t.mp3", "E", T0 + 300),         # fuera de la tolerancia de desfase
])
def test_pista_iniciada_ignora_otro_tema_otra_estacion_o_fuera_de_tolerancia(mundo, ruta, estacion, inicio):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(inicio))
    mundo.locutor.pista_iniciada(Pista(Path(ruta), 200.0, "t"), estacion)
    time.sleep(0.25)
    assert mundo.voz.cargas() == []


def test_no_suena_dos_veces_si_el_reloj_ya_habia_empezado(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 0.5))
    assert len(mundo.voz.cargas()) == 1
    mundo.locutor.pista_iniciada(Pista(Path("/m/t.mp3"), 200.0, "t"), "E")
    time.sleep(0.25)
    assert len(mundo.voz.cargas()) == 1


def test_no_suena_dos_veces_por_el_anclaje(mundo):
    mundo.locutor.registrar(mundo.iv(T0 + 0.7))
    mundo.locutor.al_sintonizar("E")                    # la ventana todavía no empezó
    assert mundo.voz.cargas() == []
    pista = Pista(Path("/m/t.mp3"), 200.0, "t")
    mundo.locutor.pista_iniciada(pista, "E")
    assert esperar(lambda: mundo.voz.cargas())
    mundo.locutor.pista_iniciada(pista, "E")
    time.sleep(0.25)
    assert len(mundo.voz.cargas()) == 1


def test_volver_a_la_estacion_dentro_de_la_ventana_retoma_la_frase(mundo):
    mundo.locutor.registrar(mundo.iv(T0 - 1))
    mundo.locutor.al_sintonizar("E")
    mundo.reloj.t += 2
    mundo.locutor.detener()
    mundo.locutor.al_sintonizar("E")
    a, b = (start_de(c) for c in mundo.voz.cargas())
    assert a == pytest.approx(1.0) and b == pytest.approx(3.0)


def test_detener_corta_la_voz_y_restaura_la_musica(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 1))
    mundo.locutor.detener()
    assert (("stop",), {}) in mundo.voz.comandos
    assert mundo.musica.llamadas[-1] == (1.0, 0.01) and not mundo.locutor.hablando


def test_al_sintonizar_otra_estacion_corta_la_voz_en_curso(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 1))
    mundo.locutor.al_sintonizar("F")
    assert (("stop",), {}) in mundo.voz.comandos
    assert mundo.musica.llamadas[-1] == (1.0, 0.01) and not mundo.locutor.hablando


def test_el_fin_del_clip_restaura_la_musica_una_sola_vez(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 1))
    mundo.voz.fin()
    assert mundo.musica.llamadas[-1] == (1.0, 0.01) and not mundo.locutor.hablando
    cuantas = len(mundo.musica.llamadas)
    mundo.voz.fin()
    assert len(mundo.musica.llamadas) == cuantas


def test_un_fin_tardio_de_un_clip_anterior_no_corta_el_nuevo(mundo):
    mundo.locutor.registrar(mundo.iv(T0 - 1))
    mundo.locutor.al_sintonizar("E")
    viejo = mundo.voz.ultimo_id
    mundo.locutor.detener()
    mundo.locutor.al_sintonizar("E")                    # empieza otro clip (otro id)
    assert mundo.voz.ultimo_id != viejo
    mundo.voz.fin(id_=viejo)                            # llega tarde el fin del primero
    assert mundo.locutor.hablando


def test_si_no_llega_el_evento_el_temporizador_de_seguridad_restaura(mundo):
    mundo.cfg = ConfigDJ(retraso_voz_segundos=0.05, rampa_bajada_segundos=0.01, rampa_subida_segundos=0.01,
                         minimo_restante_segundos=0.1, margen_seguridad_voz_segundos=0.1)
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0, dur=0.5))
    assert mundo.locutor.hablando
    assert esperar(lambda: mundo.musica.llamadas[-1] == (1.0, 0.01), timeout=1.5)
    assert not mundo.locutor.hablando


def test_error_al_cargar_el_clip_restaura_la_musica_y_no_propaga(mundo, caplog):
    caplog.set_level(logging.ERROR, logger="cassette_fm")
    mundo.voz.error = True
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 1))           # no debe lanzar
    assert mundo.musica.llamadas[-1] == (1.0, 0.01) and not mundo.locutor.hablando


def test_el_volumen_del_usuario_se_aplica_a_la_voz(mundo):
    mundo.locutor.volumen(40)
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 1))
    nombres = [c[0] for c in mundo.voz.comandos]
    assert nombres.index(("set_property", "volume", 40)) < nombres.index(("loadfile",))
    mundo.locutor.volumen(20)
    assert (("set_property", "volume", 20), {}) in mundo.voz.comandos


def test_con_volumen_cero_no_habla(mundo):
    mundo.locutor.volumen(0)
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 1))
    assert mundo.voz.cargas() == [] and mundo.musica.llamadas == []


def test_vigentes_lista_las_no_vencidas_por_inicio(mundo):
    tarde, temprano = mundo.iv(T0 + 100, estacion="E"), mundo.iv(T0 + 50, estacion="F")
    mundo.locutor.registrar(tarde)
    mundo.locutor.registrar(temprano)
    assert mundo.locutor.vigentes() == [temprano, tarde]
    mundo.reloj.t = T0 + 75
    assert mundo.locutor.vigentes() == [tarde]


def test_sintonizar_con_la_ventana_casi_terminada_no_dispara_el_anclaje(mundo):
    """Review: el primer tema tras sintonizar viene empezado; si a la voz le queda menos del mínimo, no suena."""
    mundo.locutor.registrar(mundo.iv(T0 - 7.55, dur=8.0))        # quedan 0,45 s
    mundo.locutor.al_sintonizar("E")
    assert mundo.voz.cargas() == []
    mundo.locutor.pista_iniciada(Pista(Path("/m/t.mp3"), 200.0, "t"), "E")   # file-loaded del tema en que se entró
    time.sleep(0.3)
    assert mundo.voz.cargas() == []


def test_la_voz_suena_aunque_la_musica_vaya_mas_atrasada_que_el_clip(mundo):
    """Review: el desfase de la música real puede superar la duración del clip."""
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 20, dur=8.0))          # por el reloj ya terminó hace 12 s
    assert mundo.voz.cargas() == []
    mundo.locutor.pista_iniciada(Pista(Path("/m/t.mp3"), 200.0, "t"), "E")   # el tema destino recién arranca
    assert esperar(lambda: mundo.voz.cargas())
    assert start_de(mundo.voz.cargas()[0]) == pytest.approx(0.0)


def test_una_intervencion_que_vence_sin_sonar_se_avisa_en_el_log(mundo, caplog):
    caplog.set_level(logging.WARNING, logger="cassette_fm")
    mundo.locutor.registrar(mundo.iv(T0 + 30, dur=8.0))
    mundo.reloj.t = T0 + 200                                     # pasó el fin y la gracia
    assert mundo.locutor.vigentes() == []
    assert "sin sonar" in caplog.text


def test_cerrar_cierra_la_voz(mundo):
    mundo.locutor.cerrar()
    assert mundo.voz.cerrada


def test_integracion_la_voz_entra_a_mitad_de_frase(dir_corto, tmp_path, crear_wav):
    voz = ClienteMpv(dir_corto / "voz.sock", extra_args=["--ao=null"])
    clips = tmp_path / "clips"
    registro = RegistroIntervenciones(tmp_path / "i.json", clips)
    musica = MusicaFalsa()
    loc = Locutor(voz, musica, registro, lambda n: ConfigDJ(rampa_bajada_segundos=0.01,
                                                           rampa_subida_segundos=0.01))
    try:
        loc.al_sintonizar("E")
        audio = crear_wav(clips / "x.wav", 4.0)
        ahora = time.time()
        loc.registrar(Intervencion("x", "E", ahora - 1.0, 4.0, audio, "t", "/m/t.mp3"))
        def posicion():
            try:
                return voz.comando("get_property", "time-pos") or 0
            except ErrorMpv:
                return 0      # todavía no empezó a reproducir

        assert esperar(lambda: posicion() >= 1.0, 3)
        assert musica.llamadas[0] == (CFG.nivel_musica_con_voz, 0.01)
        assert esperar(lambda: musica.llamadas[-1] == (1.0, 0.01), 6)     # el fin del clip restaura la música
    finally:
        loc.cerrar()


def test_descartar_estacion_quita_sus_intervenciones(mundo):
    a, b = mundo.iv(T0 + 100, estacion="A"), mundo.iv(T0 + 100, estacion="B")
    mundo.locutor.registrar(a)
    mundo.locutor.registrar(b)
    mundo.locutor.descartar_estacion("A")
    assert mundo.registro.todas() == [b]
    assert not a.audio.exists()


def test_descartar_estacion_corta_la_voz_si_es_de_esa_estacion(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 2))          # habla ya, desde el segundo 2
    assert mundo.locutor.hablando
    mundo.musica.llamadas.clear()
    mundo.locutor.descartar_estacion("E")
    assert not mundo.locutor.hablando
    assert (("stop",), {}) in mundo.voz.comandos
    assert mundo.musica.llamadas[-1][0] == 1.0          # la música vuelve
    assert mundo.registro.todas() == []


def test_descartar_otra_estacion_no_corta_la_voz(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 - 2))
    mundo.locutor.descartar_estacion("OTRA")
    assert mundo.locutor.hablando
    assert (("stop",), {}) not in mundo.voz.comandos


def test_descartar_la_estacion_cancela_el_anclaje_pendiente(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 + 100, destino="/m/t.mp3"))
    mundo.reloj.t = T0 + 99.96
    mundo.locutor.pista_iniciada(Pista(Path("/m/t.mp3"), 200, "t"), "E")
    mundo.locutor.descartar_estacion("E")
    time.sleep(0.2)
    assert not mundo.voz.cargas() and not mundo.locutor.hablando


@pytest.mark.parametrize("duracion", [float("nan"), 0.0, -2.0, float("inf")])
def test_registrar_rechaza_duraciones_que_no_son_un_numero_finito_positivo(mundo, duracion):
    i = mundo.iv(T0 + 100)
    malo = Intervencion(i.id, i.estacion, i.inicio, duracion, i.audio, i.texto, i.pista_destino)
    with pytest.raises(ValueError):
        mundo.locutor.registrar(malo)
    assert mundo.registro.todas() == []


def test_locutor_no_corta_ni_desancla_una_peticion_al_descartar(mundo):
    from dataclasses import replace
    mundo.locutor.al_sintonizar("E")
    pedida = replace(mundo.iv(T0 + 20), peticion="antes")
    mundo.locutor.registrar(pedida)
    mundo.locutor.pista_iniciada(Pista(Path("/m/t.mp3"), 200.0, "t"), "E")   # queda anclada
    mundo.locutor.descartar_estacion("E")
    assert esperar(lambda: mundo.voz.cargas())                               # igual habla
    assert mundo.registro.todas() == [pedida]
    mundo.locutor.descartar_estacion("E")                                    # hablando: no la corta
    assert mundo.locutor.hablando


def test_locutor_descarta_y_corta_las_normales(mundo):
    mundo.locutor.al_sintonizar("E")
    mundo.locutor.registrar(mundo.iv(T0 + 20))
    mundo.locutor.pista_iniciada(Pista(Path("/m/t.mp3"), 200.0, "t"), "E")
    mundo.locutor.descartar_estacion("E")
    time.sleep(CFG.retraso_voz_segundos + 0.3)
    assert mundo.voz.cargas() == [] and mundo.registro.todas() == []
