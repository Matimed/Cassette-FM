import unicodedata

import pytest

from cassette_fm.config import ErrorConfig
from cassette_fm.dj.lexico import Lexico


def test_busca_sin_mayusculas_ni_acentos():
    lex = Lexico({"Daddy Yankee": "en-us", "Música Ñandú": "es"})
    assert lex.idioma_de("daddy yankee", "es") == "en-us"
    assert lex.idioma_de("DADDY  YANKEE", "es") == "en-us"
    assert lex.idioma_de("musica nandu", "en-us") == "es"


def test_usa_el_defecto_si_no_esta():
    assert Lexico().idioma_de("Nadie", "es") == "es"
    assert Lexico({"A": "en-us"}).idioma_de("B", "en-gb") == "en-gb"


def test_normaliza_unicode_nfd_y_nfc():
    lex = Lexico({unicodedata.normalize("NFD", "Música"): "es"})
    assert lex.idioma_de(unicodedata.normalize("NFC", "música"), "en-us") == "es"


def test_cargar_toml(tmp_path):
    archivo = tmp_path / "lexico.toml"
    archivo.write_text('[idiomas]\n"Daddy Yankee" = "en-us"\n"Wisin & Yandel" = "es"\n')
    lex = Lexico.cargar(archivo)
    assert lex.idioma_de("daddy yankee", "es") == "en-us"
    assert lex.idioma_de("Wisin & Yandel", "en-us") == "es"


def test_cargar_ausente_es_vacio(tmp_path):
    assert Lexico.cargar(tmp_path / "no-existe.toml").idioma_de("X", "es") == "es"


@pytest.mark.parametrize("contenido", [
    "esto no es toml =",
    '[idiomas]\n"X" = 5',
    '[idiomas]\n"X" = "klingon-xyz-123"',
    'idiomas = "texto"',
])
def test_cargar_invalido_da_error_claro(tmp_path, contenido):
    archivo = tmp_path / "lexico.toml"
    archivo.write_text(contenido + "\n")
    with pytest.raises(ErrorConfig) as exc:
        Lexico.cargar(archivo)
    assert str(archivo) in str(exc.value)


def test_pronunciacion_reemplaza_la_escritura_y_busca_sin_acentos(tmp_path):
    archivo = tmp_path / "lexico.toml"
    archivo.write_text('[pronunciacion]\n"Regueton 2000" = "Reguetón 2000"\n[idiomas]\n"Nicky Jam" = "en-us"\n')
    lex = Lexico.cargar(archivo)
    assert lex.pronunciacion("regueton  2000") == "Reguetón 2000"
    assert lex.pronunciacion("Otra") == "Otra"
    assert lex.idioma_de("Nicky Jam", "es") == "en-us"


@pytest.mark.parametrize("contenido", ['pronunciacion = 3', '[pronunciacion]\nA = 3', '[pronunciacion]\nA = ""'])
def test_pronunciacion_invalida_da_ErrorConfig(tmp_path, contenido):
    archivo = tmp_path / "lexico.toml"
    archivo.write_text(contenido + "\n")
    with pytest.raises(ErrorConfig) as e:
        Lexico.cargar(archivo)
    assert str(archivo) in str(e.value)
