import threading
from pathlib import Path

import pytest

from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.config import Estado
from cassette_fm.radio import EstacionInexistente, Radio, SinEstaciones


class ReproductorFalso:
    def __init__(self):
        self.llamadas = []
        self.pista_actual = None
        self.al_cambiar_pista = None
        self.al_fallar = None

    def sintonizar(self, estacion):
        self.llamadas.append(("sintonizar", estacion.nombre))

    def detener(self):
        self.llamadas.append(("detener",))

    def volumen(self, valor):
        valor = max(0, min(100, valor))
        self.llamadas.append(("volumen", valor))
        return valor

    def posicion(self):
        return 12.34 if self.pista_actual else None

    def sintonizadas(self):
        return [l[1] for l in self.llamadas if l[0] == "sintonizar"]


def est(nombre):
    return Estacion(nombre, (Pista(Path(f"/m/{nombre}.mp3"), 100.0, f"tema de {nombre}"),))


def crear(nombres=("A", "B", "Regueton 2000"), estado=None, escanear=None, avisar=None, **extra):
    rep = ReproductorFalso()
    guardados = []
    estado = estado or Estado()
    estaciones = [est(n) for n in nombres]
    radio = Radio(rep, estaciones, estado,
                  guardar=lambda e: guardados.append((e.estacion, e.volumen)),
                  escanear=escanear or (lambda: estaciones), avisar=avisar, **extra)
    return radio, rep, guardados, estado


def test_nace_apagada_y_aplica_volumen():
    radio, rep, _, _ = crear(estado=Estado(volumen=55))
    assert radio.encendida is False
    assert ("volumen", 55) in rep.llamadas
    assert rep.sintonizadas() == []


def test_encender_sin_estado_sintoniza_la_primera():
    radio, rep, _, _ = crear()
    radio.encender()
    assert rep.sintonizadas() == ["A"]
    assert radio.encendida


def test_encender_recuerda_la_ultima():
    radio, rep, _, _ = crear(estado=Estado(estacion="B"))
    radio.encender()
    assert rep.sintonizadas() == ["B"]


def test_siguiente_y_anterior_dan_la_vuelta():
    radio, rep, _, _ = crear(estado=Estado(estacion="Regueton 2000"))
    radio.siguiente()
    radio.anterior()
    radio.anterior()
    assert rep.sintonizadas() == ["A", "Regueton 2000", "B"]


def test_siguiente_y_anterior_sin_estacion_actual():
    radio, rep, _, _ = crear()
    radio.siguiente()
    radio2, rep2, _, _ = crear()
    radio2.anterior()
    assert rep.sintonizadas() == ["A"]
    assert rep2.sintonizadas() == ["Regueton 2000"]


def test_siguiente_estando_apagada_enciende():
    radio, rep, _, _ = crear(estado=Estado(estacion="A"))
    assert not radio.encendida
    radio.siguiente()
    assert radio.encendida and rep.sintonizadas() == ["B"]


def test_sintonizar_por_prefijo_y_sin_mayusculas():
    radio, rep, _, _ = crear()
    radio.sintonizar("reg")
    radio.sintonizar("REGUETON 2000")
    assert rep.sintonizadas() == ["Regueton 2000", "Regueton 2000"]


def test_sintonizar_enciende_y_acepta_acentos():
    radio, rep, _, _ = crear(nombres=("Música Ñandú", "Zeta"))
    radio.sintonizar("música ñandú")
    assert radio.encendida and rep.sintonizadas() == ["Música Ñandú"]


def test_sintonizar_inexistente_o_ambiguo():
    radio, _, _, _ = crear(nombres=("Rock", "Rap"))
    with pytest.raises(EstacionInexistente):
        radio.sintonizar("x")
    with pytest.raises(EstacionInexistente):
        radio.sintonizar("r")


def test_coincidencia_exacta_gana_al_prefijo():
    radio, rep, _, _ = crear(nombres=("Rock", "Rocker"))
    radio.sintonizar("rock")
    assert rep.sintonizadas() == ["Rock"]


def test_sin_estaciones():
    radio, _, _, _ = crear(nombres=())
    for accion in (radio.encender, radio.siguiente, radio.anterior):
        with pytest.raises(SinEstaciones):
            accion()
    assert radio.estado()["estaciones"] == []


def test_guarda_estado_al_sintonizar_y_al_cambiar_volumen():
    radio, _, guardados, _ = crear()
    radio.sintonizar("B")
    assert guardados[-1] == ("B", 70)
    radio.volumen(valor=40)
    assert guardados[-1] == ("B", 40)


def test_volumen_delta_y_valor():
    radio, _, _, _ = crear(estado=Estado(volumen=70))
    assert radio.volumen(delta=5) == 75
    assert radio.volumen(delta=-100) == 0
    assert radio.volumen(valor=30) == 30
    assert radio.volumen() == 30


def test_apagar_detiene():
    radio, rep, _, _ = crear()
    radio.encender()
    radio.apagar()
    assert not radio.encendida and rep.llamadas[-1] == ("detener",)
    radio.alternar()
    assert radio.encendida
    radio.alternar()
    assert not radio.encendida


def test_rescan_conserva_o_reubica():
    nuevas = [est("A"), est("B")]
    radio, rep, _, _ = crear(escanear=lambda: nuevas)
    radio.sintonizar("B")
    radio.rescan()
    assert rep.sintonizadas() == ["B"]  # sigue existiendo: no se interrumpe
    nuevas[:] = [est("A")]
    radio.rescan()
    assert rep.sintonizadas() == ["B", "A"]  # desapareció: pasa a la primera
    nuevas[:] = []
    radio.rescan()
    assert not radio.encendida and rep.llamadas[-1] == ("detener",)


def test_estado_dict():
    radio, rep, _, _ = crear(estado=Estado(estacion="A", volumen=60))
    assert radio.estado() == {"encendida": False, "estacion": "A", "pista": None,
                              "volumen": 60, "estaciones": ["A", "B", "Regueton 2000"],
                              "segundo": None}
    radio.encender()
    rep.pista_actual = est("A").pistas[0]
    assert radio.estado()["pista"] == "tema de A"
    assert radio.estado()["segundo"] == 12.3
    assert radio.estado()["encendida"] is True


def test_avisa_al_cambiar_pista():
    avisos = []
    radio, rep, _, _ = crear(avisar=lambda e, t: avisos.append((e, t)))
    radio.sintonizar("A")
    rep.al_cambiar_pista(est("A").pistas[0], est("A"))
    assert avisos == [("A", "tema de A")]


def test_el_aviso_usa_la_estacion_del_evento_y_no_depende_de_encendida():
    avisos = []
    radio, rep, _, _ = crear(avisar=lambda e, t: avisos.append((e, t)))
    assert not radio.encendida
    rep.al_cambiar_pista(est("B").pistas[0], est("B"))
    assert avisos == [("B", "tema de B")]


def test_si_el_reproductor_falla_la_radio_se_apaga():
    radio, rep, _, _ = crear()
    radio.encender()
    rep.al_fallar(est("A"))
    assert not radio.encendida and rep.llamadas[-1] == ("detener",)


def test_un_aviso_de_falla_de_otra_estacion_no_apaga_la_actual():
    radio, rep, _, _ = crear()
    radio.sintonizar("B")
    rep.al_fallar(est("A"))   # la falla era de una estación que ya no suena
    assert radio.encendida and rep.sintonizadas() == ["B"]


def test_buscar_normaliza_unicode():
    import unicodedata
    nfd = unicodedata.normalize("NFD", "Música Ñandú")
    radio, rep, _, _ = crear(nombres=(nfd, "Zeta"))
    radio.sintonizar(unicodedata.normalize("NFC", "música ñandú"))
    assert rep.sintonizadas() == [nfd]


def test_rescan_no_bloquea_el_estado_mientras_escanea():
    liberar = threading.Event()
    entro = threading.Event()

    def lento():
        entro.set()
        liberar.wait(5)
        return [est("A")]

    radio, _, _, _ = crear(escanear=lento)
    hilo = threading.Thread(target=radio.rescan)
    hilo.start()
    assert entro.wait(2)
    resultado = []
    consulta = threading.Thread(target=lambda: resultado.append(radio.estado()))
    consulta.start()
    consulta.join(1)
    respondio_mientras_escaneaba = bool(resultado)
    liberar.set()
    hilo.join(2)
    assert respondio_mientras_escaneaba, "estado() quedó bloqueado por rescan"


def test_cambios_rapidos():
    radio, rep, _, _ = crear()
    hilos = [threading.Thread(target=radio.siguiente) for _ in range(10)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len(rep.sintonizadas()) == 10
    assert rep.sintonizadas()[-1] == radio.estado()["estacion"]


def test_sintonizar_fallida_no_cambia_la_estacion_ni_enciende():
    radio, rep, guardados, estado = crear(estado=Estado(estacion="A"))

    def falla(estacion):
        raise RuntimeError("mpv")

    rep.sintonizar = falla
    with pytest.raises(RuntimeError):
        radio.sintonizar("B")
    assert estado.estacion == "A" and not radio.encendida
    assert guardados == []


def test_volumen_cero_apaga():
    radio, rep, _, _ = crear(estado=Estado(volumen=10))
    radio.encender()
    assert radio.volumen(delta=-10) == 0
    assert not radio.encendida and rep.llamadas[-1] == ("detener",)


def test_subir_volumen_enciende_la_estacion_guardada():
    radio, rep, _, _ = crear(estado=Estado(estacion="B", volumen=0))
    assert radio.volumen(delta=10) == 10
    assert radio.encendida and rep.sintonizadas() == ["B"]


def test_subir_volumen_enciende_la_primera_si_no_hay_guardada():
    radio, rep, _, _ = crear(estado=Estado(volumen=0))
    radio.volumen(delta=10)
    assert radio.encendida and rep.sintonizadas() == ["A"]


def test_apagar_conserva_el_volumen_y_subir_lo_suma():
    radio, rep, _, estado = crear(estado=Estado(volumen=70))
    radio.encender()
    radio.apagar()
    assert estado.volumen == 70
    assert radio.volumen(delta=10) == 80
    assert radio.encendida


def test_bajar_volumen_apagada_no_enciende():
    radio, rep, _, _ = crear(estado=Estado(volumen=50))
    assert radio.volumen(delta=-10) == 40
    assert not radio.encendida and rep.sintonizadas() == []


def test_bajar_en_cero_apagada_sigue_apagada():
    radio, rep, _, _ = crear(estado=Estado(volumen=0))
    assert radio.volumen(delta=-10) == 0
    assert not radio.encendida and rep.sintonizadas() == []


def test_encender_con_volumen_cero_sube_a_minimo():
    radio, rep, _, _ = crear(estado=Estado(volumen=0))
    rep.llamadas.clear()
    radio.encender()
    assert radio.volumen() == 10
    assert rep.llamadas.index(("volumen", 10)) < rep.llamadas.index(("sintonizar", "A"))


def test_subir_sin_estaciones_guarda_el_volumen_y_falla():
    radio, _, _, _ = crear(nombres=(), estado=Estado(volumen=0))
    with pytest.raises(SinEstaciones):
        radio.volumen(delta=10)
    assert radio.volumen() == 10



# --- DJ (Etapa 3, parte 1) ---

import logging  # noqa: E402

from cassette_fm.agenda import EPOCA  # noqa: E402
from cassette_fm.config import ConfigDJ  # noqa: E402
from cassette_fm.radio import DJInactivo, RadioApagada  # noqa: E402


class LocutorFalso:
    def __init__(self):
        self.llamadas = []
        self.hablando = False
        self.registrados = []
        self.fallas = 0

    def al_sintonizar(self, nombre):
        self.llamadas.append(("al_sintonizar", nombre))

    def detener(self):
        self.llamadas.append(("detener",))

    def volumen(self, valor):
        self.llamadas.append(("volumen", valor))

    def pista_iniciada(self, pista, nombre):
        self.llamadas.append(("pista_iniciada", pista, nombre))

    def registrar(self, i):
        if self.fallas:
            self.fallas -= 1
            raise ValueError("se superpone con otra intervención")
        self.registrados.append(i)

    def vigentes(self):
        return list(self.registrados)


def con_dj(tmp_path, cfg=None, **kw):
    loc = LocutorFalso()
    radio, rep, guardados, estado = crear(
        dj=loc, dir_clips=tmp_path / "clips", configuracion_dj=lambda n: cfg or ConfigDJ(activo=True),
        reloj=lambda: EPOCA + 10, **kw)
    loc.llamadas = rep.llamadas          # una sola línea de tiempo para comprobar el orden
    return radio, rep, loc


def test_sintonizar_avisa_al_locutor_despues_del_reproductor(tmp_path):
    radio, rep, loc = con_dj(tmp_path)
    radio.sintonizar("B")
    assert rep.llamadas.index(("sintonizar", "B")) < rep.llamadas.index(("al_sintonizar", "B"))


def test_apagar_detiene_al_locutor(tmp_path):
    radio, rep, loc = con_dj(tmp_path)
    radio.encender()
    radio.apagar()
    assert ("detener",) in rep.llamadas and rep.llamadas.count(("detener",)) >= 2   # reproductor y locutor


def test_el_volumen_llega_al_locutor_incluso_en_cero(tmp_path):
    radio, rep, loc = con_dj(tmp_path)
    radio.encender()
    radio.volumen(valor=40)
    radio.volumen(valor=0)
    assert ("volumen", 40) in rep.llamadas and rep.llamadas.count(("volumen", 0)) >= 2


def test_el_volumen_inicial_y_el_minimo_tambien_llegan_al_locutor(tmp_path):
    loc = LocutorFalso()
    crear(estado=Estado(volumen=55), dj=loc)
    assert ("volumen", 55) in loc.llamadas
    radio, rep, loc2 = con_dj(tmp_path, estado=Estado(volumen=0))
    radio.encender()
    assert ("volumen", 10) in rep.llamadas


def test_pista_iniciada_llega_al_locutor_con_el_nombre_de_la_estacion(tmp_path):
    radio, rep, loc = con_dj(tmp_path)
    radio.sintonizar("A")
    rep.al_cambiar_pista(est("A").pistas[0], est("A"))
    assert ("pista_iniciada", est("A").pistas[0], "A") in rep.llamadas


def test_sin_locutor_todo_sigue_andando():
    radio, rep, _, _ = crear()
    radio.sintonizar("A")
    rep.al_cambiar_pista(est("A").pistas[0], est("A"))
    radio.volumen(valor=30)
    radio.apagar()
    assert radio.dj_estado() == {"activo": False, "hablando": False, "desfase_segundos": None,
                                 "intervenciones": []}


def test_el_desfase_se_mide_menos_en_el_primer_tema_de_la_sintonia(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="cassette_fm")
    cfg = ConfigDJ(activo=True, desfase_aviso_segundos=2.0)
    radio, rep, loc = con_dj(tmp_path, cfg=cfg)
    radio.sintonizar("A")
    tema = est("A")
    rep.al_cambiar_pista(tema.pistas[0], tema)                 # el tema en el que se entró: no se mide
    assert radio.dj_estado()["desfase_segundos"] is None
    rep.al_cambiar_pista(tema.pistas[0], tema)                 # reloj = EPOCA + 10: la agenda ya contó 10 s
    assert radio.dj_estado()["desfase_segundos"] == pytest.approx(10.0)
    assert "desfase" in caplog.text


def test_dj_probar_sin_dj_da_DJInactivo():
    radio, _, _, _ = crear()
    with pytest.raises(DJInactivo):
        radio.dj_probar()


def test_dj_probar_con_la_radio_apagada_da_RadioApagada(tmp_path):
    radio, _, _ = con_dj(tmp_path)
    with pytest.raises(RadioApagada):
        radio.dj_probar()


def test_dj_probar_registra_en_la_proxima_transicion_con_margen(tmp_path):
    radio, rep, loc = con_dj(tmp_path)
    radio.sintonizar("A")                                       # tema de 100 s; reloj = EPOCA + 10
    r = radio.dj_probar(en_segundos=20.0)
    i = loc.registrados[0]
    assert i.estacion == "A" and i.pista_destino == "/m/A.mp3"
    assert i.inicio == pytest.approx(EPOCA + 100 + 1.0)         # próximo tema + retraso_voz_segundos
    assert i.inicio >= EPOCA + 10 + 20
    assert i.duracion == pytest.approx(8.0, abs=0.1)
    assert i.audio.parent == tmp_path / "clips" and i.audio.exists()
    assert r["estacion"] == "A" and r["duracion"] == pytest.approx(i.duracion)


def test_dj_probar_respeta_el_margen_pedido(tmp_path):
    radio, rep, loc = con_dj(tmp_path)
    radio.sintonizar("A")
    radio.dj_probar(en_segundos=150.0)                          # el tema de EPOCA+100 ya no alcanza
    assert loc.registrados[0].inicio == pytest.approx(EPOCA + 200 + 1.0)


def test_dj_probar_salta_huecos_ocupados(tmp_path):
    radio, rep, loc = con_dj(tmp_path)
    radio.sintonizar("A")
    loc.fallas = 1
    radio.dj_probar(en_segundos=20.0)
    assert loc.registrados[0].inicio == pytest.approx(EPOCA + 200 + 1.0)
    assert len(list((tmp_path / "clips").iterdir())) == 1       # se reutiliza el mismo clip, no se copia de nuevo


def test_dj_probar_rechaza_audio_inexistente_o_demasiado_largo(tmp_path, crear_wav):
    radio, rep, loc = con_dj(tmp_path)
    radio.sintonizar("A")
    with pytest.raises(ValueError):
        radio.dj_probar(audio=tmp_path / "no-existe.wav")
    largo = crear_wav(tmp_path / "largo.wav", 20.0)
    with pytest.raises(ValueError):
        radio.dj_probar(audio=largo)
    assert loc.registrados == []
    assert not (tmp_path / "clips").exists() or list((tmp_path / "clips").iterdir()) == []


def test_dj_probar_usa_el_audio_dado(tmp_path, crear_wav):
    radio, rep, loc = con_dj(tmp_path)
    radio.sintonizar("A")
    mio = crear_wav(tmp_path / "mio.wav", 5.0)
    radio.dj_probar(audio=mio)
    assert loc.registrados[0].duracion == pytest.approx(5.0, abs=0.1)
    assert mio.exists()                                          # el original no se toca


def test_dj_estado_lista_las_intervenciones_vigentes(tmp_path):
    radio, rep, loc = con_dj(tmp_path)
    radio.sintonizar("A")
    radio.dj_probar(en_segundos=20.0)
    e = radio.dj_estado()
    assert e["activo"] is True and e["hablando"] is False
    (item,) = e["intervenciones"]
    assert item["estacion"] == "A" and item["texto"] == "(clip de prueba)"
    assert item["en_segundos"] == pytest.approx(91.0)            # (EPOCA+101) - (EPOCA+10)
