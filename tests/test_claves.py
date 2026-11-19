import json
import re
import stat
from datetime import datetime

import pytest

from cassette_fm import claves
from cassette_fm.claves import ErrorClaves, borrar, crear, generar_clave, huella, leer, para_relay

FORMATO = re.compile(r"^[0-9a-hjkmnp-tv-z]{4}(-[0-9a-hjkmnp-tv-z]{4}){3}$")


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "cfg" / "claves.json"


def test_generar_clave_formato():
    a, b = generar_clave(), generar_clave()
    assert FORMATO.match(a) and FORMATO.match(b) and a != b


def test_huella_ignora_mayusculas_guiones_y_espacios():
    h = huella("K7QM-ABCD-2345-6789")
    assert h == huella(" k7qmabcd 2345-6789 ") and re.fullmatch(r"[0-9a-f]{64}", h)


def test_crear_guarda_huella_no_la_clave(ruta):
    clave, registro = crear(ruta, "Mamá", "escucha", ahora=lambda: datetime.fromisoformat("2026-11-19T21:04:00-03:00"))
    texto = ruta.read_text()
    assert clave not in texto and claves.normalizar(clave) not in texto
    assert re.fullmatch(r"[0-9a-f]{8}", registro["id"]) and registro["huella"] == huella(clave)
    assert registro["permiso"] == "escucha" and registro["nombre"] == "Mamá"
    assert datetime.fromisoformat(registro["creada"]).utcoffset() is not None
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600
    assert leer(ruta) == [registro]


@pytest.mark.parametrize("nombre,permiso", [(" mamá ", "escucha"), ("", "escucha"), ("   ", "escucha"),
                                            ("x" * 41, "escucha"), ("a\nb", "escucha"), ("Papá", "admin")])
def test_crear_validaciones(ruta, nombre, permiso):
    crear(ruta, "Mamá", "escucha")
    antes = ruta.read_text()
    with pytest.raises(ErrorClaves):
        crear(ruta, nombre, permiso)
    assert ruta.read_text() == antes


def test_borrar(ruta):
    _, registro = crear(ruta, "Mamá", "completa")
    assert borrar(ruta, "  MAMÁ ") == registro
    assert leer(ruta) == []
    with pytest.raises(ErrorClaves):
        borrar(ruta, "Mamá")


def test_leer_ausente_es_vacia(ruta):
    assert leer(ruta) == []


@pytest.mark.parametrize("contenido", [
    "{no es json", '{"claves": 3}', '[]', '{"claves": [{"id": "abcd1234", "nombre": "x", "permiso": "escucha"}]}',
    json.dumps({"claves": [{"id": "abcd1234", "nombre": "x", "permiso": "admin", "huella": "0" * 64,
                            "creada": "2026-11-19T21:04:00-03:00"}]}),
])
def test_leer_roto(ruta, contenido):
    ruta.parent.mkdir(parents=True)
    ruta.write_text(contenido)
    with pytest.raises(ErrorClaves):
        leer(ruta)


def test_para_relay_sin_nombres(ruta):
    _, registro = crear(ruta, "Mamá", "escucha")
    salida = para_relay(leer(ruta))
    assert salida == [{"id": registro["id"], "permiso": "escucha", "huella": registro["huella"]}]
    assert "Mamá" not in json.dumps(salida) and registro["creada"] not in json.dumps(salida)


def test_ids_unicos_en_muchas_claves(ruta):
    for i in range(50):
        crear(ruta, f"p{i}", "escucha")
    ids = [r["id"] for r in leer(ruta)]
    assert len(set(ids)) == 50
