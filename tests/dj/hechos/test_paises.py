from cassette_fm.dj.hechos.paises import PAISES, nombre_de_pais


def test_ejemplos():
    assert nombre_de_pais("NO", "es") == "Noruega" and nombre_de_pais("NO", "en") == "Norway"
    assert nombre_de_pais("US", "es") == "Estados Unidos" and nombre_de_pais("US", "en") == "the United States"
    assert nombre_de_pais("GB", "es") == "Reino Unido" and nombre_de_pais("GB", "en") == "the United Kingdom"
    assert nombre_de_pais("PR", "es") == "Puerto Rico"


def test_desconocido_o_con_otra_caja():
    assert nombre_de_pais("ZZ", "es") is None
    assert nombre_de_pais("no", "es") == "Noruega"
    assert nombre_de_pais("", "es") is None and nombre_de_pais("NOR", "es") is None


def test_todos_los_codigos_tienen_los_dos_idiomas():
    assert len(PAISES) >= 55
    for codigo, (es, en) in PAISES.items():
        assert len(codigo) == 2 and codigo.isupper() and es.strip() and en.strip(), codigo
