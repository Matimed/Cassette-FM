import http.client
import json
import logging
import queue
import threading
import urllib.parse
from types import SimpleNamespace

import pytest

from cassette_fm.lan_server import crear_servidor_lan, estado_publico
from cassette_fm.lan_stream import CodificadorNoDisponible, SinCapacidad

TOKEN = "clave-de-prueba-123"
NOMBRES = ["Pop Hits F.M.", "Más Gasolina F.M.", "A/B", "¿Qué?", "100%"]


class RadioFalsa:
    def __init__(self):
        self.llamadas = []
        self.error = None

    def estado(self):
        return {"encendida": True, "estacion": "Pop Hits F.M.", "pista": "Artista - Tema", "volumen": 70,
                "monitor_local": True, "estaciones": list(NOMBRES), "fuente": "spotify", "segundo": 12.3,
                "iconos": self.iconos()}

    def iconos(self):
        return {"Pop Hits F.M.": str(self.logo), "Más Gasolina F.M.": str(self.sin_logo)}

    def estaciones(self):
        return [SimpleNamespace(nombre=n, pistas=()) for n in NOMBRES]

    def sintonizar(self, nombre, oir_aca=True):
        if self.error:
            raise self.error
        self.llamadas.append((nombre, oir_aca))


class DifusorFalso:
    def __init__(self):
        self.cola = queue.Queue()
        self.error = None
        self.desuscritos = 0

    def suscribir(self):
        if self.error:
            raise self.error
        return self.cola

    def desuscribir(self, cola):
        self.desuscritos += 1


@pytest.fixture
def servidor(tmp_path):
    radio, difusor = RadioFalsa(), DifusorFalso()
    radio.logo = tmp_path / "logo.png"
    radio.logo.write_bytes(b"\x89PNG-de-prueba")
    radio.sin_logo = tmp_path / "no-existe.png"
    srv = crear_servidor_lan(radio, difusor, TOKEN, "127.0.0.1", 0)
    hilo = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True)
    hilo.start()
    srv.radio, srv.difusor, srv.puerto = radio, difusor, srv.server_address[1]
    yield srv
    srv.shutdown()
    srv.server_close()


def pedir(srv, metodo, ruta, token=TOKEN, autorizacion=None, cuerpo=None):
    conexion = http.client.HTTPConnection("127.0.0.1", srv.puerto, timeout=5)
    cabeceras = {}
    if autorizacion is not None:
        cabeceras["Authorization"] = autorizacion
    elif token is not None:
        cabeceras["Authorization"] = f"Bearer {token}"
    conexion.request(metodo, ruta, body=cuerpo, headers=cabeceras)
    r = conexion.getresponse()
    datos = r.read()
    conexion.close()
    return r.status, r, datos


RUTAS = [("GET", "/status"), ("POST", "/station/Pop%20Hits%20F.M."), ("GET", "/stream"), ("GET", "/icon/Pop%20Hits%20F.M.")]


@pytest.mark.parametrize("metodo, ruta", RUTAS)
@pytest.mark.parametrize("autorizacion", [None, "", "Bearer ", "Bearer mala", "Basic " + TOKEN, TOKEN])
def test_sin_clave_o_con_clave_mala_401_sin_detalle(servidor, metodo, ruta, autorizacion):
    if autorizacion is None:
        codigo, _, datos = pedir(servidor, metodo, ruta, token=None)
    else:
        codigo, _, datos = pedir(servidor, metodo, ruta, autorizacion=autorizacion)
    assert codigo == 401
    assert TOKEN.encode() not in datos and b"mala" not in datos
    assert servidor.radio.llamadas == []


@pytest.mark.parametrize("metodo, ruta", [("GET", "/estado"), ("GET", "/volumen"), ("POST", "/volumen"), ("GET", "/dj"),
                                          ("POST", "/apagar"), ("GET", "/"), ("GET", "/status/x")])
def test_otras_rutas_404_aunque_no_haya_clave(servidor, metodo, ruta):
    assert pedir(servidor, metodo, ruta, token=None)[0] == 404
    assert pedir(servidor, metodo, ruta)[0] == 404
    assert servidor.radio.llamadas == []


@pytest.mark.parametrize("metodo", ["PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_metodos_no_previstos_405_y_no_ejecutan_nada(servidor, metodo):
    assert pedir(servidor, metodo, "/stream")[0] == 405
    assert pedir(servidor, metodo, "/station/Pop%20Hits%20F.M.")[0] == 405
    assert servidor.radio.llamadas == [] and servidor.difusor.desuscritos == 0


def test_status_trae_solo_los_campos_publicos(servidor):
    codigo, r, datos = pedir(servidor, "GET", "/status")
    cuerpo = json.loads(datos)
    assert codigo == 200 and r.getheader("Content-Type").startswith("application/json")
    assert set(cuerpo) == {"encendida", "estacion", "pista", "estaciones", "fuente", "segundo", "iconos"}
    assert list(cuerpo["iconos"]) == ["Pop Hits F.M."] and cuerpo["estaciones"] == NOMBRES
    assert b"volumen" not in datos and b"monitor_local" not in datos and b"/home/usuario" not in datos


def test_estado_publico_no_inventa_campos():
    assert estado_publico({"volumen": 1, "monitor_local": True}) == {
        "encendida": None, "estacion": None, "pista": None, "estaciones": [], "fuente": None, "segundo": None,
        "iconos": {}}


def test_station_sintoniza_sin_oir_aca_y_devuelve_el_estado_publico(servidor):
    codigo, _, datos = pedir(servidor, "POST", "/station/M%C3%A1s%20Gasolina%20F.M.")
    assert codigo == 200 and "estaciones" in json.loads(datos)
    assert servidor.radio.llamadas == [("Más Gasolina F.M.", False)]


@pytest.mark.parametrize("nombre", ["A/B", "¿Qué?", "100%", "Pop Hits F.M."])
def test_station_ida_y_vuelta_de_nombres_con_caracteres_raros(servidor, nombre):
    ruta = "/station/" + urllib.parse.quote(nombre, safe="")
    assert pedir(servidor, "POST", ruta)[0] == 200
    assert servidor.radio.llamadas[-1] == (nombre, False)


@pytest.mark.parametrize("nombre", ["Pop", "pop hits f.m.", "", "Inexistente"])
def test_station_inexistente_404_sin_sintonia_aproximada(servidor, nombre):
    assert pedir(servidor, "POST", "/station/" + urllib.parse.quote(nombre, safe=""))[0] == 404
    assert servidor.radio.llamadas == []


def test_stream_entrega_los_bytes_del_difusor_con_los_headers(servidor):
    servidor.difusor.cola.put(b"ID3-uno")
    servidor.difusor.cola.put(b"dos")
    servidor.difusor.cola.put(None)
    codigo, r, datos = pedir(servidor, "GET", "/stream")
    assert codigo == 200 and datos == b"ID3-unodos"
    assert r.getheader("Content-Type") == "audio/mpeg" and r.getheader("Content-Length") is None
    assert r.getheader("Cache-Control") == "no-store"
    assert servidor.difusor.desuscritos == 1


def test_stream_se_desuscribe_cuando_el_cliente_corta(servidor):
    conexion = http.client.HTTPConnection("127.0.0.1", servidor.puerto, timeout=5)
    conexion.request("GET", "/stream", headers={"Authorization": f"Bearer {TOKEN}"})
    r = conexion.getresponse()
    servidor.difusor.cola.put(b"x" * 100)
    assert r.read(100) == b"x" * 100
    r.close()                      # el socket sigue abierto mientras la respuesta lo use
    conexion.close()
    for _ in range(200):
        servidor.difusor.cola.put(b"x" * 4096)
        if servidor.difusor.desuscritos:
            break
        threading.Event().wait(0.02)
    assert servidor.difusor.desuscritos == 1


@pytest.mark.parametrize("error", [SinCapacidad("ya hay 4 oyentes"), CodificadorNoDisponible("falta gst-launch-1.0")])
def test_stream_503_con_el_motivo(servidor, error):
    servidor.difusor.error = error
    codigo, _, datos = pedir(servidor, "GET", "/stream")
    assert codigo == 503 and str(error).encode() in datos


def test_la_clave_no_aparece_en_los_logs(servidor, caplog):
    caplog.set_level(logging.DEBUG)
    pedir(servidor, "GET", "/status")
    pedir(servidor, "GET", "/status", token="otra-clave-secreta")
    pedir(servidor, "POST", "/station/Inexistente")
    assert TOKEN not in caplog.text and "otra-clave-secreta" not in caplog.text


def test_status_trae_los_logos_como_urls_versionadas_sin_rutas_locales(servidor):
    _, _, datos = pedir(servidor, "GET", "/status")
    iconos = json.loads(datos)["iconos"]
    assert list(iconos) == ["Pop Hits F.M."]                       # el archivo que no existe no se publica
    assert iconos["Pop Hits F.M."].startswith("/icon/Pop%20Hits%20F.M.?v=") and len(iconos["Pop Hits F.M."]) > 30
    assert str(servidor.radio.logo.parent).encode() not in datos


def test_la_version_del_logo_cambia_cuando_cambia_el_archivo(servidor):
    antes = json.loads(pedir(servidor, "GET", "/status")[2])["iconos"]["Pop Hits F.M."]
    servidor.radio.logo.write_bytes(b"\x89PNG-otro-logo-mas-largo")
    despues = json.loads(pedir(servidor, "GET", "/status")[2])["iconos"]["Pop Hits F.M."]
    assert antes != despues


def test_icon_content_type_etag_y_cuerpo(servidor):
    codigo, r, datos = pedir(servidor, "GET", "/icon/Pop%20Hits%20F.M.")
    assert codigo == 200 and datos == b"\x89PNG-de-prueba"
    assert r.getheader("Content-Type") == "image/png" and r.getheader("ETag")
    assert r.getheader("Content-Length") == str(len(datos))


def test_icon_conditional_get_devuelve_304(servidor):
    etag = pedir(servidor, "GET", "/icon/Pop%20Hits%20F.M.")[1].getheader("ETag")
    conexion = http.client.HTTPConnection("127.0.0.1", servidor.puerto, timeout=5)
    conexion.request("GET", "/icon/Pop%20Hits%20F.M.", headers={"Authorization": f"Bearer {TOKEN}", "If-None-Match": etag})
    r = conexion.getresponse()
    assert r.status == 304 and r.read() == b""
    conexion.close()


def test_icon_jpeg_y_otras_extensiones(servidor, tmp_path):
    jpg = tmp_path / "foto.JPG"
    jpg.write_bytes(b"\xff\xd8jpeg")
    servidor.radio.iconos = lambda: {"Pop Hits F.M.": str(jpg)}
    assert pedir(servidor, "GET", "/icon/Pop%20Hits%20F.M.")[1].getheader("Content-Type") == "image/jpeg"
    texto = tmp_path / "secreto.txt"
    texto.write_text("no es una imagen")
    servidor.radio.iconos = lambda: {"Pop Hits F.M.": str(texto)}
    assert pedir(servidor, "GET", "/icon/Pop%20Hits%20F.M.")[0] == 404          # solo se sirven imágenes
    assert "iconos" in json.loads(pedir(servidor, "GET", "/status")[2]) and \
        json.loads(pedir(servidor, "GET", "/status")[2])["iconos"] == {}


@pytest.mark.parametrize("ruta", ["/icon/..%2F..%2Fetc%2Fpasswd", "/icon/%2Fetc%2Fpasswd", "/icon/Inexistente",
                                  "/icon/M%C3%A1s%20Gasolina%20F.M.", "/icon/", "/icon/Pop%20Hits%20F.M./x"])
def test_icon_sirve_solo_los_logos_registrados_y_nunca_una_ruta_del_cliente(servidor, ruta):
    assert pedir(servidor, "GET", ruta)[0] == 404
