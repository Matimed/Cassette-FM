import random
from datetime import datetime
from itertools import islice
from pathlib import Path

import pytest

from cassette_fm.agenda import secuencia, transiciones
from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.config import ConfigDJ, Frecuencia
from cassette_fm.planificacion import Hueco, Ultima, armar_pedido, elegir_hueco

AHORA = 1_800_000_000.0


def pista(n, con_tags=True, duracion=200.0, **extra):
    datos = dict(artista=f"Artista {n}", cancion=f"Tema {n}") if con_tags else {}
    datos.update(extra)
    return Pista(Path(f"/m/E/{n:02d}.mp3"), duracion, f"Artista {n} - Tema {n}", **datos)


def estacion(n=12, **kw):
    return Estacion("E", tuple(pista(i, **kw) for i in range(n)))


def cfg(**kw):
    kw.setdefault("margen_minutos", 0.0)
    return ConfigDJ(**kw)


def indice(est, ahora, hueco):
    """Número de transición (1 = el tema que sigue al actual) del tema destino."""
    for j, (_, t) in enumerate(transiciones(est, ahora), start=1):
        if t == hueco.inicio_tema:
            return j
    raise AssertionError


def test_temas_sin_ultima_cae_entre_min_y_max_temas_desde_ahora():
    est = estacion()
    c = cfg(frecuencia=Frecuencia("temas", 2, 4))
    vistos = set()
    for semilla in range(200):
        h = elegir_hueco(est, AHORA, c, None, random.Random(semilla))
        j = indice(est, AHORA, h)
        assert 2 <= j <= 4
        vistos.add(j)
    assert vistos == {2, 3, 4}


def test_temas_con_ultima_cuenta_desde_la_ultima():
    est = estacion()
    c = cfg(frecuencia=Frecuencia("temas", 3, 5))
    inicio = next(t for _, t in transiciones(est, AHORA - 250))   # un borde real, entre 50 y 250 s atrás
    serie = [t for _, t in islice(transiciones(est, inicio - 0.001), 50)]     # serie[0] == inicio
    assert serie[0] == inicio
    vistos = set()
    for semilla in range(200):
        h = elegir_hueco(est, AHORA, c, Ultima(inicio, inicio + 10), random.Random(semilla))
        vistos.add(serie.index(h.inicio_tema))
    assert vistos == {3, 4, 5}


def test_respeta_el_margen_y_toma_la_primera_posterior():
    est = estacion()
    c = cfg(margen_minutos=10, frecuencia=Frecuencia("temas", 1, 2))   # 1..2 temas caen antes de 10 min
    for semilla in range(50):
        h = elegir_hueco(est, AHORA, c, None, random.Random(semilla))
        assert h.inicio_tema >= AHORA + 600
        primera_valida = next(t for _, t in transiciones(est, AHORA) if t >= AHORA + 600)
        assert h.inicio_tema == primera_valida


def test_margen_con_rango_que_cae_despues_del_margen_no_cambia_nada():
    est = estacion()
    c = cfg(margen_minutos=1, frecuencia=Frecuencia("temas", 5, 5))
    h = elegir_hueco(est, AHORA, c, None, random.Random(1))
    assert indice(est, AHORA, h) == 5


def test_modo_minutos():
    est = estacion()
    c = cfg(frecuencia=Frecuencia("minutos", 8, 15))
    ultima = Ultima(inicio_tema=AHORA - 300, fin=AHORA - 60)
    for semilla in range(100):
        h = elegir_hueco(est, AHORA, c, ultima, random.Random(semilla))
        assert h.inicio_tema >= ultima.fin + 8 * 60
        anterior_inicio = h.inicio_tema - h.anterior.duracion
        assert anterior_inicio < ultima.fin + 15 * 60
    for semilla in range(100):
        h = elegir_hueco(est, AHORA, c, None, random.Random(semilla))
        assert h.inicio_tema >= AHORA + 8 * 60
        assert h.inicio_tema - h.anterior.duracion < AHORA + 15 * 60


def test_la_frecuencia_de_la_config_manda():
    est = estacion()
    for n in (5, 3):
        h = elegir_hueco(est, AHORA, cfg(frecuencia=Frecuencia("temas", n, n)), None, random.Random(0))
        assert indice(est, AHORA, h) == n


def test_saltea_temas_sin_artista_o_cancion():
    pistas = [pista(i, con_tags=(i % 2 == 0)) for i in range(12)]
    est = Estacion("E", tuple(pistas))
    c = cfg(frecuencia=Frecuencia("temas", 1, 1))
    for semilla in range(20):
        h = elegir_hueco(est, AHORA, c, None, random.Random(semilla))
        assert h.pista.artista and h.pista.cancion
    sin_tags = Estacion("E", tuple(pista(i, con_tags=False) for i in range(5)))
    assert elegir_hueco(sin_tags, AHORA, c, None, random.Random(1)) is None


def test_saltea_los_huecos_ocupados():
    est = estacion()
    c = cfg(frecuencia=Frecuencia("temas", 2, 2))
    natural = elegir_hueco(est, AHORA, c, None, random.Random(0))
    ocupado = [(natural.inicio_voz - 1, natural.inicio_voz + 5)]
    h = elegir_hueco(est, AHORA, c, None, random.Random(0), ocupado)
    assert h.inicio_tema > natural.inicio_tema
    # un hueco ocupado más allá de la duración máxima de la voz no molesta
    lejos = [(natural.inicio_voz + c.duracion_maxima_segundos, natural.inicio_voz + 60)]
    assert elegir_hueco(est, AHORA, c, None, random.Random(0), lejos).inicio_tema == natural.inicio_tema


def test_anterior_es_el_tema_que_sonaba_antes():
    est = estacion()
    h = elegir_hueco(est, AHORA, cfg(), None, random.Random(3))
    antes, _ = next(secuencia(est, h.inicio_tema - 0.001))
    assert h.anterior == antes and h.anterior != h.pista


def test_hueco_inicio_voz_suma_el_retraso():
    h = elegir_hueco(estacion(), AHORA, cfg(retraso_voz_segundos=2.5), None, random.Random(1))
    assert h.inicio_voz == h.inicio_tema + 2.5


def test_sin_candidatas_da_None():
    unico = Estacion("E", (pista(0, con_tags=False),))
    assert elegir_hueco(unico, AHORA, cfg(), None, random.Random(1)) is None
    est = estacion()
    todo = [(AHORA - 10, AHORA + 10 ** 7)]
    assert elegir_hueco(est, AHORA, cfg(), None, random.Random(1), todo) is None


def test_es_determinista_con_la_misma_semilla():
    est = estacion()
    c = cfg(frecuencia=Frecuencia("temas", 1, 6))
    a = elegir_hueco(est, AHORA, c, None, random.Random(42))
    b = elegir_hueco(est, AHORA, c, None, random.Random(42))
    assert a == b


# --- armar_pedido ---

def hueco_de(est, **kw):
    return elegir_hueco(est, AHORA, cfg(**kw), None, random.Random(1))


def test_pedido_completo():
    est = Estacion("E", tuple(pista(i, album=f"Disco {i}", isrc=f"ESA0100000{i:02d}") for i in range(12)))
    c = cfg(voz="am_michael", idioma="en", personalidad="sarcástico", duracion_maxima_segundos=12.0)
    h = elegir_hueco(est, AHORA, c, None, random.Random(1))
    p = armar_pedido("abc123", "E", h, c, ["hora", "tema"])
    assert p["id"] == "abc123" and p["estacion"] == "E"
    assert (p["idioma"], p["voz"], p["personalidad"]) == ("en", "am_michael", "sarcástico")
    momento = datetime.fromisoformat(p["momento"])
    assert momento.tzinfo is not None and momento.timestamp() == pytest.approx(h.inicio_voz, abs=1)
    assert p["siguiente"] == {"artista": h.pista.artista, "titulo": h.pista.cancion, "album": h.pista.album,
                              "isrc": h.pista.isrc}
    assert p["anterior"]["artista"] == h.anterior.artista and p["anterior"]["titulo"] == h.anterior.cancion
    assert p["duracion_maxima_segundos"] == 12.0
    recientes = ["hora"]
    assert armar_pedido("x", "E", h, c, recientes)["recientes"] == ["hora"] and recientes == ["hora"]


def test_pedido_minimo():
    est = estacion()
    h = hueco_de(est)
    p = armar_pedido("x1", "E", h, cfg(), [])
    assert "personalidad" not in p
    assert set(p["siguiente"]) == {"artista", "titulo"}
    assert p["recientes"] == []


def test_el_anterior_sin_artista_no_va():
    pistas = [pista(i, con_tags=(i != 2)) for i in range(5)]
    est = Estacion("E", tuple(pistas))
    h = Hueco(pistas[3], AHORA + 100, AHORA + 101, pistas[2])
    assert "anterior" not in armar_pedido("x", "E", h, cfg(), [])
    h = Hueco(pistas[3], AHORA + 100, AHORA + 101, None)
    assert "anterior" not in armar_pedido("x", "E", h, cfg(), [])


def test_el_pedido_pasa_la_validacion_del_servicio():
    from cassette_fm.dj.pedido import leer_pedido
    pistas = [Pista(Path(f"/m/{i}.mp3"), 200.0, "x", artista=f'Guns "N" Roses {i}', cancion="Sweet Child o' Mine ñandú",
                    album="Ápice", isrc="ES1234567890") for i in range(6)]
    est = Estacion("Rock \"duro\" ñ", tuple(pistas))
    h = elegir_hueco(est, AHORA, cfg(), None, random.Random(1))
    pedido = leer_pedido(armar_pedido("a-b_1", est.nombre, h, cfg(personalidad="cálido"), ["x"]))
    assert pedido.siguiente.artista.startswith("Guns")
