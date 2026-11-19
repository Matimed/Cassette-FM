import pytest

from cassette_relay.config import CALIDADES, PROTOCOLO, ErrorConfig, desde_entorno


def test_constantes_del_protocolo():
    assert CALIDADES == (64, 96, 160) and PROTOCOLO == 1


def test_lee_las_variables():
    a = desde_entorno({"INGEST_TOKEN": "t" * 40, "APP_PASSWORD": "clave-larga", "PORT": "10000"})
    assert (a.ingest_token, a.app_password, a.puerto) == ("t" * 40, "clave-larga", 10000)


def test_puerto_por_defecto():
    assert desde_entorno({"INGEST_TOKEN": "t", "APP_PASSWORD": "12345678"}).puerto == 8080


@pytest.mark.parametrize("env, falta", [
    ({"APP_PASSWORD": "12345678"}, "INGEST_TOKEN"),
    ({"INGEST_TOKEN": "t"}, "APP_PASSWORD"),
    ({"INGEST_TOKEN": "  ", "APP_PASSWORD": "12345678"}, "INGEST_TOKEN"),
])
def test_falta_una_obligatoria(env, falta):
    with pytest.raises(ErrorConfig, match=falta):
        desde_entorno(env)


def test_clave_corta_sin_mostrarla():
    with pytest.raises(ErrorConfig, match="APP_PASSWORD") as e:
        desde_entorno({"INGEST_TOKEN": "t", "APP_PASSWORD": "corta12"})
    assert "corta12" not in str(e.value)


@pytest.mark.parametrize("puerto", ["ochenta", "0", "70000"])
def test_puerto_invalido(puerto):
    with pytest.raises(ErrorConfig, match="PORT"):
        desde_entorno({"INGEST_TOKEN": "t", "APP_PASSWORD": "12345678", "PORT": puerto})
