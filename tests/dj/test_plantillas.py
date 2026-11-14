import random
import re
from datetime import datetime, timedelta, timezone

import pytest

from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import Pedido, Tema
from cassette_fm.dj.plantillas import Redaccion, frase_hora, redactar
from cassette_fm.dj.texto_voz import limpiar

ZONA = timezone(timedelta(hours=-3))
MARCA = re.compile(r"\{([A-Za-z-]+):([^{}]*)\}")


def a(h, m):
    return datetime(2026, 11, 13, h, m, tzinfo=ZONA)


def pedido(idioma="es", album=True, anterior=True, momento=None, siguiente=("Foreigner", "Waiting for a Girl Like You")):
    return Pedido(
        id="x", estacion="Lentos", idioma=idioma, voz="v", momento=momento or a(21, 47),
        anterior=Tema("Whitesnake", "Is This Love", "Slip of the Tongue") if anterior else None,
        siguiente=Tema(siguiente[0], siguiente[1], "Records" if album else None),
    )


def palabras(r):
    return len(MARCA.sub(lambda m: m.group(2), r.marcado).split())


# --- frase_hora ---

@pytest.mark.parametrize("h,m,esperado", [
    (9, 0, "las nueve en punto"), (9, 2, "las nueve en punto"), (9, 3, "las nueve y cinco"),
    (9, 30, "las nueve y media"), (9, 47, "las diez menos cuarto"), (9, 48, "las diez menos diez"),
    (9, 53, "las diez menos cinco"), (9, 58, "las diez en punto"), (13, 0, "la una en punto"),
    (0, 0, "las doce en punto"), (12, 15, "las doce y cuarto"), (23, 50, "las doce menos diez"),
    (12, 50, "la una menos diez"), (9, 10, "las nueve y diez"), (9, 20, "las nueve y veinte"),
    (9, 25, "las nueve y veinticinco"), (9, 35, "las diez menos veinticinco"), (9, 40, "las diez menos veinte"),
])
def test_frase_hora_es(h, m, esperado):
    assert frase_hora(a(h, m), "es") == esperado


@pytest.mark.parametrize("h,m,esperado", [
    (9, 0, "nine o'clock"), (9, 15, "quarter past nine"), (9, 30, "half past nine"),
    (9, 45, "quarter to ten"), (21, 50, "ten to ten"), (23, 58, "twelve o'clock"),
    (9, 5, "five past nine"), (9, 25, "twenty five past nine"), (9, 35, "twenty five to ten"),
])
def test_frase_hora_en(h, m, esperado):
    for idioma in ("en", "en-us", "en-gb"):
        assert frase_hora(a(h, m), idioma) == esperado


def test_nunca_hay_digitos_en_la_hora():
    for idioma in ("es", "en"):
        for minutos in range(0, 24 * 60, 7):
            assert not re.search(r"\d", frase_hora(a(minutos // 60, minutos % 60), idioma))


# --- redactar ---

def test_redactar_marca_los_nombres_con_el_idioma_del_lexico():
    p = pedido(siguiente=("Daddy Yankee", "Gasolina"))
    lex = Lexico({"Daddy Yankee": "en-us"})
    vistos = 0
    for s in range(200):
        r = redactar(p, lex, random.Random(s), 45)
        sin_marcas = MARCA.sub("", r.marcado)
        assert "Daddy Yankee" not in sin_marcas            # nunca sin marcar
        for lang, nombre in MARCA.findall(r.marcado):
            assert lang == ("en-us" if nombre == "Daddy Yankee" else "es")
            vistos += nombre == "Daddy Yankee"
    assert vistos > 100


@pytest.mark.parametrize("idioma", ["es", "en", "en-gb"])
@pytest.mark.parametrize("album,anterior", [(True, True), (False, False), (True, False), (False, True)])
@pytest.mark.parametrize("hora", [(7, 10), (15, 30), (21, 47), (2, 5)])
def test_invariantes_de_todas_las_plantillas(idioma, album, anterior, hora):
    p = pedido(idioma, album, anterior, a(*hora))
    for s in range(300):
        r = redactar(p, Lexico(), random.Random(s), 45)
        assert isinstance(r, Redaccion)
        assert not re.search("[¡!¿]", r.marcado)
        limpio = limpiar(r.marcado, p.lang)
        original = re.split(r"(?<=[.?])\s+", r.marcado.strip())
        despues = re.split(r"(?<=[.?])\s+", limpio.strip())
        assert len(despues) == len(original)               # ninguna oración se unió: ninguna era corta
        for oracion in despues:
            assert len(MARCA.sub(lambda m: m.group(2), oracion).split()) >= 4
        assert palabras(r) <= 45
        assert "cancion" in r.ingredientes
        assert not re.search(r"\d", MARCA.sub("", r.marcado))   # la hora y todo lo que pone la plantilla, sin dígitos


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_hay_variedad_real(idioma):
    p = pedido(idioma)
    ingredientes, esqueletos = set(), set()
    for s in range(300):
        r = redactar(p, Lexico(), random.Random(s), 45)
        ingredientes.add(r.ingredientes)
        esqueletos.add(MARCA.sub("N", r.marcado))
    assert len(ingredientes) >= 5 and len(esqueletos) >= 5


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_una_plantilla_con_album_solo_si_el_pedido_lo_trae(idioma):
    sin = pedido(idioma, album=False)
    con = pedido(idioma, album=True)
    assert all("album" not in redactar(sin, Lexico(), random.Random(s), 45).ingredientes for s in range(200))
    assert any("album" in redactar(con, Lexico(), random.Random(s), 45).ingredientes for s in range(200))
    for s in range(200):
        r = redactar(sin, Lexico(), random.Random(s), 45)
        assert "Records" not in r.marcado


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_una_plantilla_con_anterior_solo_si_hay_anterior(idioma):
    sin = pedido(idioma, anterior=False)
    assert all("anterior" not in redactar(sin, Lexico(), random.Random(s), 45).ingredientes for s in range(200))
    assert all("Whitesnake" not in redactar(sin, Lexico(), random.Random(s), 45).marcado for s in range(200))
    assert any("anterior" in redactar(pedido(idioma), Lexico(), random.Random(s), 45).ingredientes for s in range(200))


def test_respeta_palabras_maximas():
    p = pedido("es")
    minimo_global = min(palabras(redactar(p, Lexico(), random.Random(s), 1000)) for s in range(300))
    for s in range(100):
        r = redactar(p, Lexico(), random.Random(s), 12)
        assert palabras(r) <= max(12, minimo_global)


def test_nombres_con_comillas_y_ampersand():
    p = pedido(siguiente=('Héctor "El Father"', "Zion & Lennox"))
    for s in range(100):
        r = redactar(p, Lexico(), random.Random(s), 45)
        assert '"' not in r.marcado
        limpio = limpiar(r.marcado, p.lang)
        assert "&" not in limpio and "{" in limpio


def test_el_momento_del_dia_se_adapta():
    textos = {redactar(pedido("es", momento=a(h, 0)), Lexico(), random.Random(s), 45).marcado
              for h in (8, 15, 23) for s in range(100)}
    junto = " ".join(textos)
    assert "esta mañana" in junto and "esta tarde" in junto and "esta noche" in junto


def test_es_determinista_con_la_misma_semilla():
    p = pedido("es")
    assert redactar(p, Lexico(), random.Random(7), 45) == redactar(p, Lexico(), random.Random(7), 45)
