import pytest

from cassette_fm import claves as claves_pc
from cassette_relay.acceso import DURACION_SESION, Acceso, Identidad, clave_igual, huella, normalizar
from cassette_relay.config import MAESTRA

CLAVE = "clave-correcta"
GENERADA = "k7qm-abcd-2345-6789"
LISTA = [{"id": "abcd1234", "permiso": "escucha", "huella": huella(GENERADA)}]


@pytest.fixture
def ahora():
    return [1000.0]


@pytest.fixture
def acceso(ahora):
    return Acceso(CLAVE, reloj=lambda: ahora[0])


def test_duracion_de_la_sesion():
    assert DURACION_SESION == 180 * 24 * 3600


def test_huella_igual_a_la_de_la_pc():
    for dada in ("K7QM-ABCD-2345-6789", " k7qmabcd23456789 ", "ÁÉ ñ", "", "a-b c"):
        assert huella(dada) == claves_pc.huella(dada) and normalizar(dada) == claves_pc.normalizar(dada)
    generada = claves_pc.generar_clave()
    assert normalizar(generada) == generada.replace("-", "")


def test_probar_maestra(acceso):
    assert acceso.probar(CLAVE) == ("ok", Identidad(MAESTRA, "completa"))
    assert acceso.probar("mala") == ("mal", None)
    assert acceso.probar(None) == ("mal", None)


def test_probar_clave_generada_aun_en_mayusculas_y_con_guiones(acceso):
    acceso.poner_claves(LISTA)
    esperado = ("ok", Identidad("abcd1234", "escucha"))
    assert acceso.probar(GENERADA) == esperado
    assert acceso.probar("K7QM ABCD 2345 6789") == esperado
    assert acceso.probar("k7qmabcd23456789") == esperado


def test_clave_generada_no_entra_antes_de_la_primera_lista(acceso):
    assert acceso.probar(GENERADA) == ("mal", None)


def test_clave_borrada_no_entra(acceso):
    acceso.poner_claves(LISTA)
    acceso.poner_claves([])
    assert acceso.probar(GENERADA) == ("mal", None)


def test_probar_basura_enorme_es_mal(acceso):
    assert acceso.probar("x" * 4096) == ("mal", None)


def test_sesion_de_ida_y_vuelta_maestra_y_generada(acceso):
    maestra = Identidad(MAESTRA, "completa")
    assert acceso.identidad_de_sesion(acceso.nueva_sesion(maestra)) == maestra
    acceso.poner_claves(LISTA)
    generada = Identidad("abcd1234", "escucha")
    assert acceso.identidad_de_sesion(acceso.nueva_sesion(generada)) == generada


def test_sesion_de_clave_borrada_vale_solo_antes_de_la_primera_lista(acceso):
    sesion = acceso.nueva_sesion(Identidad("abcd1234", "escucha"))
    assert acceso.identidad_de_sesion(sesion) == Identidad("abcd1234", "escucha")      # relay recién despierto
    acceso.poner_claves([{"id": "0f0f0f0f", "permiso": "completa", "huella": "b" * 64}])
    assert acceso.identidad_de_sesion(sesion) is None
    acceso.poner_claves([])
    assert acceso.identidad_de_sesion(sesion) is None


def test_la_sesion_maestra_sobrevive_a_cualquier_lista(acceso):
    sesion = acceso.nueva_sesion(Identidad(MAESTRA, "completa"))
    acceso.poner_claves([])
    assert acceso.identidad_de_sesion(sesion) == Identidad(MAESTRA, "completa")


def test_sesion_toma_el_permiso_de_la_lista(acceso):
    sesion = acceso.nueva_sesion(Identidad("abcd1234", "escucha"))
    acceso.poner_claves([{"id": "abcd1234", "permiso": "completa", "huella": "a" * 64}])
    assert acceso.identidad_de_sesion(sesion) == Identidad("abcd1234", "completa")


def test_sesion_adulterada(acceso, ahora):
    sesion = acceso.nueva_sesion(Identidad("abcd1234", "escucha"))
    ident, permiso, vence, firma = sesion.split(".")
    assert acceso.identidad_de_sesion(f"{ident}.completa.{vence}.{firma}") is None
    assert acceso.identidad_de_sesion(f"otroid123.{permiso}.{vence}.{firma}") is None
    assert acceso.identidad_de_sesion(f"{ident}.{permiso}.{int(vence) + 1000}.{firma}") is None
    assert Acceso("otra-clave-1", reloj=lambda: ahora[0]).identidad_de_sesion(sesion) is None


def test_sesion_vencida(acceso, ahora):
    sesion = acceso.nueva_sesion(Identidad(MAESTRA, "completa"))
    ahora[0] += DURACION_SESION + 1
    assert acceso.identidad_de_sesion(sesion) is None


@pytest.mark.parametrize("basura", [None, "", "basura", ".", "x.y", "1.2.3", "a.b.c.d.e", "1.escucha.²3.ab",
                                    "abcd1234.escucha." + "9" * 5000 + ".x", "abcd1234.root.99999999999.ff",
                                    "maestra.escucha.99999999999.ff"])
def test_cookie_con_basura_es_none(acceso, basura):
    assert acceso.identidad_de_sesion(basura) is None


def test_bloqueo_tras_cinco_fallos(acceso, ahora):
    for _ in range(5):
        assert acceso.probar("mala")[0] == "mal"
    assert acceso.probar(CLAVE) == ("bloqueado", None)
    ahora[0] += 61
    assert acceso.probar(CLAVE)[0] == "ok"


def test_fallos_viejos_no_cuentan(acceso, ahora):
    for _ in range(4):
        acceso.probar("mala")
    ahora[0] += 61
    acceso.probar("mala")
    assert acceso.probar(CLAVE)[0] == "ok"


def test_la_sesion_sigue_valida_durante_el_bloqueo(acceso):
    sesion = acceso.nueva_sesion(Identidad(MAESTRA, "completa"))
    for _ in range(5):
        acceso.probar("mala")
    assert acceso.probar(CLAVE)[0] == "bloqueado"
    assert acceso.identidad_de_sesion(sesion) is not None


def test_cookie_invalida_no_suma_fallos(acceso):
    for i in range(100):
        assert acceso.identidad_de_sesion(f"abcd1234.escucha.{i}.00") is None
    assert acceso.probar(CLAVE)[0] == "ok"


def test_clave_igual():
    assert clave_igual("abc", "abc") is True
    assert clave_igual("abd", "abc") is False
    assert clave_igual(None, "abc") is False
    assert clave_igual("", "") is False
    assert clave_igual("ñandú", "ñandú") is True


# --- validar_claves ---

from cassette_relay.acceso import validar_claves  # noqa: E402


def _c(ident="abcd1234", permiso="escucha", h="a" * 64):
    return {"id": ident, "permiso": permiso, "huella": h}


def test_validar_claves_validas():
    assert validar_claves([_c(), _c("0f0f0f0f", "completa", "b" * 64)]) == [_c(), _c("0f0f0f0f", "completa", "b" * 64)]
    assert validar_claves([]) == []
    assert validar_claves([{**_c(), "nombre": "Mamá"}]) == [_c()]            # un campo de más se descarta
    assert validar_claves([_c(f"{i:08x}") for i in range(200)]) is not None


@pytest.mark.parametrize("datos", [
    None, {}, "x", 3, [_c(f"{i:08x}") for i in range(201)], [_c(), _c()], [_c("abc1234")], [_c("abcd12345")],
    [_c("ABCD1234")], [_c("abcd123g")], [_c(permiso="admin")], [_c(permiso=None)], [_c(h="a" * 63)],
    [_c(h="g" * 64)], [_c(h=5)], [3], ["x"], [None], [{"id": "abcd1234"}], [_c(ident=12345678)],
])
def test_validar_claves_invalidas(datos):
    assert validar_claves(datos) is None
