import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from cassette_fm.api import crear_servidor
from cassette_fm.mpv import ErrorMpv
from cassette_fm.radio import EstacionInexistente, SinEstaciones


class RadioFalsa:
    def __init__(self):
        self.llamadas = []
        self.error = None

    def _hacer(self, nombre, *args, **kw):
        self.llamadas.append((nombre, args, kw))
        if self.error:
            raise self.error
        return None

    def estado(self):
        return {"encendida": True, "estacion": "A", "pista": "t", "volumen": 70,
                "estaciones": ["A", "B"]}

    def estaciones(self):
        return [SimpleNamespace(nombre="A", pistas=(1, 2)), SimpleNamespace(nombre="B", pistas=(1,))]

    def sintonizar(self, nombre): self._hacer("sintonizar", nombre)
    def siguiente(self): self._hacer("siguiente")
    def anterior(self): self._hacer("anterior")
    def encender(self): self._hacer("encender")
    def apagar(self): self._hacer("apagar")
    def alternar(self): self._hacer("alternar")
    def rescan(self): self._hacer("rescan")

    def volumen(self, valor=None, delta=None):
        self._hacer("volumen", valor=valor, delta=delta)
        return 0


@pytest.fixture
def servidor():
    radio = RadioFalsa()
    srv = crear_servidor(radio, "127.0.0.1", 0, raiz=Path("/home/x/Música"))
    hilo = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True)
    hilo.start()
    srv.base = f"http://127.0.0.1:{srv.server_address[1]}"
    srv.radio = radio
    yield srv
    srv.shutdown()
    srv.server_close()


def pedir(srv, metodo, ruta, cuerpo=None, crudo=None):
    datos = crudo if crudo is not None else (
        json.dumps(cuerpo, ensure_ascii=False).encode() if cuerpo is not None else None)
    req = urllib.request.Request(srv.base + ruta, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            assert r.headers["Content-Type"] == "application/json; charset=utf-8"
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_get_estado(servidor):
    codigo, cuerpo = pedir(servidor, "GET", "/estado")
    assert codigo == 200 and cuerpo == servidor.radio.estado()


def test_get_estaciones(servidor):
    assert pedir(servidor, "GET", "/estaciones") == (
        200, [{"nombre": "A", "pistas": 2}, {"nombre": "B", "pistas": 1}])


def test_post_sintonizar_con_espacios_y_acentos(servidor):
    codigo, _ = pedir(servidor, "POST", "/sintonizar", {"estacion": "Música Ñandú 2000"})
    assert codigo == 200
    assert servidor.radio.llamadas == [("sintonizar", ("Música Ñandú 2000",), {})]


@pytest.mark.parametrize("ruta", ["siguiente", "anterior", "encender", "apagar", "alternar", "rescan"])
def test_post_acciones_simples(servidor, ruta):
    codigo, cuerpo = pedir(servidor, "POST", f"/{ruta}")
    assert codigo == 200 and cuerpo["estacion"] == "A"
    assert servidor.radio.llamadas == [(ruta, (), {})]


def test_volumen_valor_y_delta(servidor):
    pedir(servidor, "POST", "/volumen", {"valor": 40})
    pedir(servidor, "POST", "/volumen", {"delta": -5})
    assert servidor.radio.llamadas == [("volumen", (), {"valor": 40, "delta": None}),
                                       ("volumen", (), {"valor": None, "delta": -5})]


def test_volumen_sin_campos_400(servidor):
    assert pedir(servidor, "POST", "/volumen", {})[0] == 400


def test_estacion_inexistente_404(servidor):
    servidor.radio.error = EstacionInexistente("la estación 'x' no existe")
    codigo, cuerpo = pedir(servidor, "POST", "/sintonizar", {"estacion": "x"})
    assert codigo == 404 and "no existe" in cuerpo["error"]


def test_json_invalido_400(servidor):
    codigo, cuerpo = pedir(servidor, "POST", "/sintonizar", crudo=b"{no es json")
    assert codigo == 400 and "error" in cuerpo


def test_sintonizar_sin_campo_400(servidor):
    assert pedir(servidor, "POST", "/sintonizar", {"otra": 1})[0] == 400


def test_sin_estaciones_409_nombra_la_raiz(servidor):
    servidor.radio.error = SinEstaciones("no hay estaciones")
    codigo, cuerpo = pedir(servidor, "POST", "/encender")
    assert codigo == 409 and "/home/x/Música" in cuerpo["error"]


def test_ruta_desconocida_404(servidor):
    assert pedir(servidor, "GET", "/nada")[0] == 404
    assert pedir(servidor, "POST", "/nada")[0] == 404


def test_error_de_mpv_503(servidor):
    servidor.radio.error = ErrorMpv("mpv no respondió a 'loadfile'")
    codigo, cuerpo = pedir(servidor, "POST", "/siguiente")
    assert codigo == 503 and "mpv" in cuerpo["error"]


@pytest.mark.parametrize("cuerpo", [{"valor": "x", "delta": 5}, {"delta": "5"}, {"valor": 1.5}])
def test_volumen_con_tipos_invalidos_400(servidor, cuerpo):
    assert pedir(servidor, "POST", "/volumen", cuerpo)[0] == 400
    assert servidor.radio.llamadas == []


def test_error_inesperado_500_y_se_loguea(servidor, caplog):
    servidor.radio.error = RuntimeError("explotó")
    codigo, cuerpo = pedir(servidor, "POST", "/siguiente")
    assert codigo == 500 and "error" in cuerpo
    assert "explotó" in caplog.text
