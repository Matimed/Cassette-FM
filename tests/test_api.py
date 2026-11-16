import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from cassette_fm.api import crear_servidor
from cassette_fm.mpv import ErrorMpv
from cassette_fm.radio import DJInactivo, RadioApagada, EstacionInexistente, SinEstaciones


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

    def dj_estado(self):
        return {"activo": True, "hablando": False, "desfase_segundos": 0.4, "intervenciones": []}

    def dj_probar(self, audio=None, en_segundos=20.0):
        self._hacer("dj_probar", audio=audio, en_segundos=en_segundos)
        return {"estacion": "A", "inicio": 1.0, "duracion": 8.0, "pista_destino": "/m/t.mp3", "en_segundos": 20.0}

    def dj_modo(self, nuevo=None):
        self._hacer("dj_modo", nuevo=nuevo)
        return {"modo": nuevo or "plantillas", **({"llm": "ok"} if nuevo == "llm" else {})}

    def dj_pedir(self, en_segundos=20.0):
        self._hacer("dj_pedir", en_segundos=en_segundos)
        return {"id": "x", "estacion": "A", "inicio": 1.0, "en_segundos": en_segundos, "tema": "Artista - Tema"}

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
    srv = crear_servidor(radio, "127.0.0.1", 0, emisoras=Path("/home/x/.config/cassette-fm/estaciones.json"))
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


def test_sin_estaciones_409_nombra_el_archivo_de_emisoras(servidor):
    servidor.radio.error = SinEstaciones("no hay estaciones")
    codigo, cuerpo = pedir(servidor, "POST", "/encender")
    assert codigo == 409 and "/home/x/.config/cassette-fm/estaciones.json" in cuerpo["error"]


def test_rescan_con_config_rota_es_400(servidor):
    from cassette_fm.config import ErrorConfig
    servidor.radio.error = ErrorConfig("x/estaciones.json: línea 3, columna 1: Expecting value")
    codigo, cuerpo = pedir(servidor, "POST", "/rescan")
    assert codigo == 400 and "línea 3" in cuerpo["error"]


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


def test_get_dj(servidor):
    assert pedir(servidor, "GET", "/dj") == (200, servidor.radio.dj_estado())


def test_post_dj_probar_pasa_audio_y_en_segundos(servidor):
    codigo, cuerpo = pedir(servidor, "POST", "/dj/probar", {"audio": "/tmp/x.wav", "en_segundos": 30})
    assert codigo == 200 and cuerpo["pista_destino"] == "/m/t.mp3"
    (llamada,) = servidor.radio.llamadas
    assert llamada[0] == "dj_probar"
    assert str(llamada[2]["audio"]) == "/tmp/x.wav" and llamada[2]["en_segundos"] == 30.0


def test_post_dj_probar_sin_cuerpo_usa_los_valores_por_defecto(servidor):
    assert pedir(servidor, "POST", "/dj/probar")[0] == 200
    assert servidor.radio.llamadas[0][2] == {"audio": None, "en_segundos": 20.0}


def test_dj_inactivo_409(servidor):
    servidor.radio.error = DJInactivo("apagado")
    codigo, cuerpo = pedir(servidor, "POST", "/dj/probar")
    assert codigo == 409 and "activo = true" in cuerpo["error"] and "[dj]" in cuerpo["error"]


def test_radio_apagada_409(servidor):
    servidor.radio.error = RadioApagada("apagada")
    codigo, cuerpo = pedir(servidor, "POST", "/dj/probar")
    assert codigo == 409 and "encendé la radio" in cuerpo["error"]


def test_dj_probar_valueerror_400(servidor):
    servidor.radio.error = ValueError("el clip dura 20.0 s y el máximo es 15 s")
    codigo, cuerpo = pedir(servidor, "POST", "/dj/probar")
    assert codigo == 400 and "el clip dura 20.0 s" in cuerpo["error"]


@pytest.mark.parametrize("cuerpo", [{"en_segundos": "x"}, {"audio": 5}, {"en_segundos": True}])
def test_dj_probar_tipos_invalidos_400(servidor, cuerpo):
    assert pedir(servidor, "POST", "/dj/probar", cuerpo)[0] == 400
    assert servidor.radio.llamadas == []


def test_post_dj_pedir_pasa_en_segundos(servidor):
    codigo, cuerpo = pedir(servidor, "POST", "/dj/pedir", {"en_segundos": 45})
    assert codigo == 200 and cuerpo["id"] == "x" and cuerpo["en_segundos"] == 45.0
    assert servidor.radio.llamadas == [("dj_pedir", (), {"en_segundos": 45.0})]


def test_post_dj_pedir_sin_cuerpo_usa_el_valor_por_defecto(servidor):
    assert pedir(servidor, "POST", "/dj/pedir")[0] == 200
    assert servidor.radio.llamadas[0][2] == {"en_segundos": 20.0}


def test_post_dj_pedir_dj_inactivo_409_menciona_la_url(servidor):
    servidor.radio.error = DJInactivo("sin planificador")
    codigo, cuerpo = pedir(servidor, "POST", "/dj/pedir")
    assert codigo == 409 and "url" in cuerpo["error"] and "[dj]" in cuerpo["error"]


def test_post_dj_pedir_radio_apagada_409(servidor):
    servidor.radio.error = RadioApagada("apagada")
    assert pedir(servidor, "POST", "/dj/pedir")[0] == 409


def test_post_dj_pedir_valueerror_400(servidor):
    servidor.radio.error = ValueError("ya hay un pedido en curso")
    codigo, cuerpo = pedir(servidor, "POST", "/dj/pedir")
    assert codigo == 400 and "en curso" in cuerpo["error"]


@pytest.mark.parametrize("cuerpo", [{"en_segundos": "x"}, {"en_segundos": True}, {"en_segundos": -1},
                                    {"en_segundos": None}])
def test_post_dj_pedir_tipos_invalidos_400(servidor, cuerpo):
    assert pedir(servidor, "POST", "/dj/pedir", cuerpo)[0] == 400
    assert servidor.radio.llamadas == []


def test_get_dj_modo(servidor):
    assert pedir(servidor, "GET", "/dj/modo") == (200, {"modo": "plantillas"})
    assert servidor.radio.llamadas == [("dj_modo", (), {"nuevo": None})]


def test_post_dj_modo_pasa_el_modo(servidor):
    assert pedir(servidor, "POST", "/dj/modo", {"modo": "llm"}) == (200, {"modo": "llm", "llm": "ok"})
    assert pedir(servidor, "POST", "/dj/modo", {"modo": "plantillas"}) == (200, {"modo": "plantillas"})
    assert [l[2]["nuevo"] for l in servidor.radio.llamadas] == ["llm", "plantillas"]


def test_post_dj_modo_apagado(servidor):
    assert pedir(servidor, "POST", "/dj/modo", {"modo": "apagado"}) == (200, {"modo": "apagado"})
    assert servidor.radio.llamadas[-1][2]["nuevo"] == "apagado"


def test_dj_modo_inactivo_409(servidor):
    servidor.radio.error = DJInactivo("sin planificador")
    for metodo, cuerpo in (("GET", None), ("POST", {"modo": "llm"})):
        codigo, resp = pedir(servidor, metodo, "/dj/modo", cuerpo)
        assert codigo == 409 and "url" in resp["error"]


def test_dj_modo_valueerror_400(servidor):
    servidor.radio.error = ValueError("el servicio DJ no responde en http://x")
    for metodo, cuerpo in (("GET", None), ("POST", {"modo": "llm"})):
        codigo, resp = pedir(servidor, metodo, "/dj/modo", cuerpo)
        assert codigo == 400 and "no responde" in resp["error"]


@pytest.mark.parametrize("cuerpo", [{}, {"modo": "otro"}, {"modo": 3}, {"modo": None}])
def test_post_dj_modo_invalido_400(servidor, cuerpo):
    assert pedir(servidor, "POST", "/dj/modo", cuerpo)[0] == 400
    assert servidor.radio.llamadas == []
