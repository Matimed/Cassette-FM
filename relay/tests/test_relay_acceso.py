import pytest

from cassette_relay.acceso import DURACION_SESION, Acceso, clave_igual

CLAVE = "clave-correcta"


@pytest.fixture
def ahora():
    return [1000.0]


@pytest.fixture
def acceso(ahora):
    return Acceso(CLAVE, reloj=lambda: ahora[0])


def test_duracion_de_la_sesion():
    assert DURACION_SESION == 180 * 24 * 3600


def test_sesion_de_ida_y_vuelta(acceso):
    assert acceso.sesion_valida(acceso.nueva_sesion()) is True


def test_sesion_vencida(acceso, ahora):
    sesion = acceso.nueva_sesion()
    ahora[0] += DURACION_SESION + 1
    assert acceso.sesion_valida(sesion) is False


def test_sesion_adulterada(acceso):
    vence, firma = acceso.nueva_sesion().split(".")
    otra_firma = ("0" if firma[0] != "0" else "1") + firma[1:]
    assert acceso.sesion_valida(f"{vence}.{otra_firma}") is False
    assert acceso.sesion_valida(f"{int(vence) + 1000}.{firma}") is False
    for basura in (None, "", "basura", ".", "x.y", "1.2.3"):
        assert acceso.sesion_valida(basura) is False


def test_otra_clave_invalida_la_sesion(acceso, ahora):
    assert Acceso("otra-clave-1", reloj=lambda: ahora[0]).sesion_valida(acceso.nueva_sesion()) is False


def test_probar(acceso):
    assert acceso.probar(CLAVE) == "ok"
    assert acceso.probar("mala") == "mal"
    assert acceso.probar(None) == "mal"


def test_bloqueo_tras_cinco_fallos(acceso, ahora):
    for _ in range(5):
        assert acceso.probar("mala") == "mal"
    assert acceso.probar(CLAVE) == "bloqueado"
    ahora[0] += 61
    assert acceso.probar(CLAVE) == "ok"


def test_fallos_viejos_no_cuentan(acceso, ahora):
    for _ in range(4):
        acceso.probar("mala")
    ahora[0] += 61
    acceso.probar("mala")
    assert acceso.probar(CLAVE) == "ok"


def test_la_sesion_sigue_valida_durante_el_bloqueo(acceso):
    sesion = acceso.nueva_sesion()
    for _ in range(5):
        acceso.probar("mala")
    assert acceso.probar(CLAVE) == "bloqueado"
    assert acceso.sesion_valida(sesion) is True


def test_clave_igual():
    assert clave_igual("abc", "abc") is True
    assert clave_igual("abd", "abc") is False
    assert clave_igual(None, "abc") is False
    assert clave_igual("", "") is False
    assert clave_igual("ñandú", "ñandú") is True
