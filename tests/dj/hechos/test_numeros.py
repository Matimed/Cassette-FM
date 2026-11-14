import pytest

from cassette_fm.dj.hechos.numeros import anio_en_palabras, en_palabras


@pytest.mark.parametrize("n, es, en", [
    (0, "cero", "zero"), (1, "uno", "one"), (15, "quince", "fifteen"), (21, "veintiuno", "twenty one"),
    (22, "veintidós", "twenty two"), (30, "treinta", "thirty"), (45, "cuarenta y cinco", "forty five"),
    (99, "noventa y nueve", "ninety nine"), (-1, "menos uno", "minus one"), (-3, "menos tres", "minus three"),
    (10, "diez", "ten"), (16, "dieciséis", "sixteen"), (20, "veinte", "twenty"), (-99, "menos noventa y nueve", "minus ninety nine"),
])
def test_en_palabras(n, es, en):
    assert en_palabras(n, "es") == es and en_palabras(n, "en") == en


@pytest.mark.parametrize("n", [1000, -1000, 10000])
def test_en_palabras_fuera_de_rango(n):
    with pytest.raises(ValueError):
        en_palabras(n, "es")


@pytest.mark.parametrize("a, es, en", [
    (1984, "mil novecientos ochenta y cuatro", "nineteen eighty four"),
    (1999, "mil novecientos noventa y nueve", "nineteen ninety nine"),
    (1900, "mil novecientos", "nineteen hundred"),
    (1905, "mil novecientos cinco", "nineteen oh five"),
    (2000, "dos mil", "two thousand"),
    (2010, "dos mil diez", "twenty ten"),
    (2021, "dos mil veintiuno", "twenty twenty one"),
    (2026, "dos mil veintiséis", "twenty twenty six"),
    (2005, "dos mil cinco", "two thousand five"),
])
def test_anio_en_palabras(a, es, en):
    assert anio_en_palabras(a, "es") == es and anio_en_palabras(a, "en") == en


@pytest.mark.parametrize("a", [1899, 2100, 0])
def test_anio_fuera_de_rango(a):
    with pytest.raises(ValueError):
        anio_en_palabras(a, "es")


def test_idioma_invalido():
    with pytest.raises(ValueError):
        en_palabras(1, "fr")


@pytest.mark.parametrize("n, es, en", [
    (100, "cien", "one hundred"), (101, "ciento uno", "one hundred one"), (200, "doscientos", "two hundred"),
    (250, "doscientos cincuenta", "two hundred fifty"), (500, "quinientos", "five hundred"),
    (999, "novecientos noventa y nueve", "nine hundred ninety nine"), (721, "setecientos veintiuno", "seven hundred twenty one"),
])
def test_centenas(n, es, en):
    assert en_palabras(n, "es") == es and en_palabras(n, "en") == en
