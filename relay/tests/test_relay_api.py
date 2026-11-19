import http.client
import json
import socket
import threading
import time
import urllib.parse

import pytest

from ayudas_relay import (AJUSTES_RAPIDOS, CASA, CLAVE, OYENTES, TOKEN, RelayEnHilo, casa, esperar, pc_en_linea,
                          recibir_tipo)

BEARER = {"Authorization": f"Bearer {CLAVE}"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 50


def _cookie(headers):
    crudo = headers.get("Set-Cookie", "")
    return crudo, crudo.split(";", 1)[0]          # ("sesion=…; HttpOnly; …", "sesion=…")


def _entrar(relay, clave=CLAVE, headers=None):
    return relay.pedir("POST", "/api/entrar", {"clave": clave}, headers)


def _contestar(ws, tipo, ok=True, error=None):
    def hilo():
        m = recibir_tipo(ws, tipo)
        r = {"tipo": "resultado", "id": m["id"], "ok": ok}
        if error:
            r["error"] = error
        ws.send(json.dumps(r))
        hilo.recibido = m
    t = threading.Thread(target=hilo, daemon=True)
    t.start()
    return hilo


def test_api_sin_acceso_401(relay):
    status, _, cuerpo = relay.pedir("GET", "/api/estado")
    assert status == 401 and "error" in json.loads(cuerpo)


def test_entrar_pone_cookie(relay):
    status, headers, _ = _entrar(relay)
    assert status == 204
    crudo, cookie = _cookie(headers)
    assert cookie.startswith("sesion=") and len(cookie) > 20
    assert "HttpOnly" in crudo and "SameSite=Lax" in crudo and "Max-Age=15552000" in crudo and "Path=/" in crudo
    assert "Secure" not in crudo
    assert relay.pedir("GET", "/api/estado", headers={"Cookie": cookie})[0] == 200


def test_cookie_secure_detras_del_proxy(relay):
    _, headers, _ = _entrar(relay, headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in _cookie(headers)[0]


def test_cookie_adulterada_401(relay):
    assert relay.pedir("GET", "/api/estado", headers={"Cookie": "sesion=99999999999.abc"})[0] == 401


@pytest.mark.parametrize("valor", ["1.escucha.\u00b23.ab", "abcd1234.escucha." + "9" * 5000 + ".x", "a.b.c.d.e"])
def test_cookie_con_basura_da_401_no_500(relay, valor):
    assert relay.pedir("GET", "/api/estado", headers={"Cookie": f"sesion={valor}"})[0] == 401


def test_bearer_correcto_y_malo(relay):
    assert relay.pedir("GET", "/api/estado", headers=BEARER)[0] == 200
    assert relay.pedir("GET", "/api/estado", headers={"Authorization": "Bearer otra"})[0] == 401


def test_entrar_clave_mala_y_bloqueo(relay):
    _, headers, _ = _entrar(relay)
    cookie = _cookie(headers)[1]
    for _ in range(5):
        assert _entrar(relay, "mala-clave")[0] == 401
    assert _entrar(relay)[0] == 429
    assert relay.pedir("GET", "/api/estado", headers=BEARER)[0] == 429
    assert relay.pedir("GET", "/api/estado", headers={"Cookie": cookie})[0] == 200


def test_entrar_exige_json(relay):
    status, _, _ = relay.pedir("POST", "/api/entrar", json.dumps({"clave": CLAVE}).encode(),
                               {"Content-Type": "text/plain"})
    assert status == 415
    assert relay.pedir("POST", "/api/entrar", b"{roto", {"Content-Type": "application/json"})[0] == 400


def test_salir_borra_la_cookie(relay):
    _, headers, _ = _entrar(relay)
    status, headers, _ = relay.pedir("POST", "/api/salir", {}, {"Cookie": _cookie(headers)[1]})
    assert status == 204
    crudo, cookie = _cookie(headers)
    assert cookie in ("sesion=", 'sesion=""') and "Max-Age=0" in crudo


def test_estado_fuera_de_linea(relay):
    status, _, cuerpo = relay.pedir("GET", "/api/estado", headers=BEARER)
    assert json.loads(cuerpo) == {"en_linea": False, "visto_hace": None, "calidades": [64, 96, 160], "radio": None,
                               "permiso": "completa"}


def test_estado_en_linea(relay):
    pc_en_linea(relay)
    e = json.loads(relay.pedir("GET", "/api/estado", headers=BEARER)[2])
    assert e["en_linea"] is True and e["visto_hace"] is None
    assert e["radio"]["estacion"] == "A" and "tipo" not in e["radio"] and "seq" not in e["radio"]


def test_estado_conserva_lo_ultimo_al_irse_la_pc(relay):
    pc_en_linea(relay).close()
    assert esperar(lambda: not relay.en_loop(lambda: relay.app[CASA].en_linea))
    e = json.loads(relay.pedir("GET", "/api/estado", headers=BEARER)[2])
    assert e["en_linea"] is False and e["visto_hace"] >= 0 and e["radio"]["estacion"] == "A"


def test_sintonizar(relay):
    ws = pc_en_linea(relay)
    hilo = _contestar(ws, "sintonizar")
    status, _, cuerpo = relay.pedir("POST", "/api/sintonizar", {"estacion": "a/b?c"}, BEARER)
    assert (status, json.loads(cuerpo)) == (200, {"ok": True}) and hilo.recibido["estacion"] == "a/b?c"


def test_sintonizar_rechazado(relay):
    ws = pc_en_linea(relay)
    _contestar(ws, "sintonizar", ok=False, error="esa emisora no existe")
    status, _, cuerpo = relay.pedir("POST", "/api/sintonizar", {"estacion": "Z"}, BEARER)
    assert (status, json.loads(cuerpo)) == (409, {"error": "esa emisora no existe"})


@pytest.mark.parametrize("cuerpo", [{"estacion": ""}, {"estacion": 3}, {}, ["A"]])
def test_sintonizar_invalido(relay, cuerpo):
    pc_en_linea(relay)
    assert relay.pedir("POST", "/api/sintonizar", cuerpo, BEARER)[0] == 400


def test_ordenes_exigen_json(relay):
    pc_en_linea(relay)
    headers = {**BEARER, "Content-Type": "text/plain"}
    assert relay.pedir("POST", "/api/sintonizar", b'{"estacion": "A"}', headers)[0] == 415
    assert relay.pedir("POST", "/api/siguiente", b"", headers)[0] == 415


def test_siguiente_y_anterior(relay):
    ws = pc_en_linea(relay)
    for tipo in ("siguiente", "anterior"):
        _contestar(ws, tipo)
        assert relay.pedir("POST", f"/api/{tipo}", {}, BEARER)[0] == 200


def test_siguiente_fuera_de_linea(relay):
    status, _, cuerpo = relay.pedir("POST", "/api/siguiente", {}, BEARER)
    assert (status, json.loads(cuerpo)) == (503, {"error": "la radio está fuera de línea"})


def test_icono(relay):
    nombre = "Más Gasolina F.M."
    pc_en_linea(relay, iconos={nombre: "v1"})
    ruta = "/api/icono/" + urllib.parse.quote(nombre, safe="")
    assert relay.pedir("PUT", ruta.replace("/api/", "/casa/") + "?v=v1", PNG,
                       {"Content-Type": "image/png", "Authorization": f"Bearer {TOKEN}"})[0] == 204
    status, headers, datos = relay.pedir("GET", ruta + "?v=v1", headers=BEARER)
    assert status == 200 and datos == PNG and headers["Content-Type"] == "image/png"
    assert "immutable" in headers["Cache-Control"]
    assert relay.pedir("GET", ruta, headers=BEARER)[1]["Cache-Control"] == "no-cache"
    assert relay.pedir("GET", "/api/icono/desconocida", headers=BEARER)[0] == 404
    assert relay.pedir("GET", ruta)[0] == 401


def test_escuchar_fuera_de_linea_503(relay):
    assert relay.pedir("GET", "/api/escuchar?calidad=64", headers=BEARER)[0] == 503


@pytest.mark.parametrize("calidad", ["128", "abc"])
def test_escuchar_calidad_invalida_400(relay, calidad):
    pc_en_linea(relay)
    assert relay.pedir("GET", f"/api/escuchar?calidad={calidad}", headers=BEARER)[0] == 400


def _escuchar(relay, calidad=64, headers=BEARER):
    conexion = http.client.HTTPConnection("127.0.0.1", relay.puerto, timeout=5)
    conexion.request("GET", f"/api/escuchar?calidad={calidad}", headers=headers)
    return conexion, conexion.getresponse()


def test_escuchar_recibe_audio(relay):
    ws = pc_en_linea(relay)
    conexion, r = _escuchar(relay)
    assert r.status == 200 and r.headers["Content-Type"] == "audio/mpeg" and r.headers["Cache-Control"] == "no-store"
    assert recibir_tipo(ws, "demanda") == {"tipo": "demanda", "calidades": [64]}
    audio = casa(relay, "/casa/audio?calidad=64")
    audio.send(b"x" * 1000)
    assert r.read(1000) == b"x" * 1000
    conexion.close()


def test_escuchar_con_cookie(relay):
    pc_en_linea(relay)
    cookie = _cookie(_entrar(relay)[1])[1]
    conexion, r = _escuchar(relay, 96, {"Cookie": cookie})
    assert r.status == 200
    conexion.close()


@pytest.fixture
def relay_paciente():
    """Con 10 s de tolerancia sin audio: que el oyente salga por irse, no por el corte de sin_audio."""
    r = RelayEnHilo(**{**AJUSTES_RAPIDOS, "sin_audio": 10.0})
    yield r
    r.cerrar()


def test_oyente_que_se_va_sin_audio_sale_de_la_cuenta(relay_paciente):
    relay = relay_paciente
    ws = pc_en_linea(relay)
    conexion, r = _escuchar(relay)
    assert r.status == 200
    recibir_tipo(ws, "demanda")
    conexion.close()
    r.close()
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 0, timeout=3)
    assert recibir_tipo(ws, "demanda") == {"tipo": "demanda", "calidades": []}


def test_oyente_lento_no_frena_a_los_demas(relay):
    ws = pc_en_linea(relay)
    lento = socket.socket()
    lento.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    lento.connect(("127.0.0.1", relay.puerto))
    lento.sendall(f"GET /api/escuchar?calidad=64 HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {CLAVE}\r\n\r\n".encode())
    conexion, rapido = _escuchar(relay)
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 2)
    recibir_tipo(ws, "demanda")
    audio = casa(relay, "/casa/audio?calidad=64")
    total = bytearray()
    lector = threading.Thread(target=lambda: total.extend(rapido.read(400 * 1024)), daemon=True)
    lector.start()
    for i in range(100):
        audio.send(bytes([i]) * 4096)
        time.sleep(0.01)
    lector.join(5)
    assert bytes(total) == b"".join(bytes([i]) * 4096 for i in range(100))
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 1, timeout=3)
    lento.close()
    conexion.close()


def test_oyente_sin_audio_se_corta(relay):
    pc_en_linea(relay)
    conexion, r = _escuchar(relay)
    inicio = time.monotonic()
    assert r.read() == b""
    assert time.monotonic() - inicio < 2.5
    conexion.close()


def test_pagina_publica(relay):
    status, headers, cuerpo = relay.pedir("GET", "/")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert b"/api/entrar" in cuerpo and b"/api/escuchar" in cuerpo


def test_head_de_escuchar_no_suma_oyente(relay):
    ws = pc_en_linea(relay)
    status, headers, cuerpo = relay.pedir("HEAD", "/api/escuchar?calidad=64", headers=BEARER)
    assert status == 200 and headers["Content-Type"] == "audio/mpeg" and cuerpo == b""
    assert relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 0
    with pytest.raises(AssertionError):
        recibir_tipo(ws, "demanda", timeout=0.5)


def test_cuerpo_grande_sin_clave_413(relay):
    grande = json.dumps({"clave": "x" * 10_000}).encode()
    assert relay.pedir("POST", "/api/entrar", grande, {"Content-Type": "application/json"})[0] == 413


def test_cuerpo_grande_en_trozos_413(relay):
    s = socket.create_connection(("127.0.0.1", relay.puerto), timeout=5)
    s.sendall(b"POST /api/entrar HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
              b"Transfer-Encoding: chunked\r\n\r\n")
    for _ in range(10):
        s.sendall(b"400\r\n" + b"x" * 1024 + b"\r\n")
    s.sendall(b"0\r\n\r\n")
    assert s.recv(100).startswith(b"HTTP/1.1 413")
    s.close()


# --- claves: corte del audio de las claves borradas ---

from ayudas_relay import ACCESO  # noqa: E402
from cassette_relay.acceso import huella  # noqa: E402

GENERADA = "k7qm-abcd-2345-6789"
BEARER_GENERADA = {"Authorization": f"Bearer {GENERADA}"}


def _lista(permiso="escucha", ident="abcd1234"):
    return [{"id": ident, "permiso": permiso, "huella": huella(GENERADA)}]


def _mandar_claves(ws, claves):
    ws.send(json.dumps({"tipo": "claves", "claves": claves}))


def _generada_entra(relay):
    return relay.pedir("POST", "/api/entrar", {"clave": GENERADA})[0]


def test_la_clave_generada_entra_solo_despues_de_la_lista(relay):
    ws = pc_en_linea(relay)
    assert _generada_entra(relay) == 401
    _mandar_claves(ws, _lista())
    assert esperar(lambda: _generada_entra(relay) == 204)


def _audio_abierto(relay, ws, headers):
    conexion, r = _escuchar(relay, 64, headers)
    assert r.status == 200
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) >= 1)
    return conexion, r


@pytest.mark.parametrize("lista_nueva", [[], _lista(ident="0f0f0f0f")])
def test_borrar_la_clave_corta_su_audio_y_no_el_de_la_maestra(relay, lista_nueva):
    ws = pc_en_linea(relay)
    _mandar_claves(ws, _lista())
    assert esperar(lambda: _generada_entra(relay) == 204)
    conexion, r = _audio_abierto(relay, ws, BEARER_GENERADA)
    maestra, rm = _escuchar(relay, 64, BEARER)
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 2)
    _mandar_claves(ws, lista_nueva)
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 1)
    assert r.read() == b""                                        # el audio de la clave borrada terminó
    audio = casa(relay, "/casa/audio?calidad=64")
    audio.send(b"y" * 100)
    assert rm.read(100) == b"y" * 100                             # el de la maestra sigue
    conexion.close()
    maestra.close()


def test_sesion_de_la_gracia_con_id_que_la_primera_lista_no_trae_se_corta(relay):
    # el relay "recién despertó": nunca recibió una lista, y una cookie firmada con un id de clave todavía vale
    acceso = relay.app[ACCESO]
    from cassette_relay.acceso import Identidad
    cookie = relay.en_loop(lambda: acceso.nueva_sesion(Identidad("abcd1234", "escucha")))
    ws = pc_en_linea(relay)
    conexion, r = _audio_abierto(relay, ws, {"Cookie": f"sesion={cookie}"})
    _mandar_claves(ws, _lista(ident="0f0f0f0f"))
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 0)
    assert r.read() == b""
    conexion.close()


# --- permisos ---

BEARER_MAESTRA = BEARER


def _con_clave(relay, ws, permiso):
    _mandar_claves(ws, _lista(permiso))
    assert esperar(lambda: _generada_entra(relay) == 204)


def _cookie_de_generada(relay):
    return _cookie(relay.pedir("POST", "/api/entrar", {"clave": GENERADA})[1])[1]


@pytest.mark.parametrize("ruta,cuerpo", [("/api/sintonizar", {"estacion": "B"}), ("/api/siguiente", {}),
                                         ("/api/anterior", {}), ("/api/sintonizar", None)])
@pytest.mark.parametrize("como", ["bearer", "cookie"])
def test_escucha_no_puede_dar_ordenes(relay, ruta, cuerpo, como):
    ws = pc_en_linea(relay)
    _con_clave(relay, ws, "escucha")
    headers = BEARER_GENERADA if como == "bearer" else {"Cookie": _cookie_de_generada(relay)}
    if cuerpo is None:                                               # ni siquiera se mira el cuerpo
        status, _, datos = relay.pedir("POST", ruta, b"no es json", {**headers, "Content-Type": "text/plain"})
    else:
        status, _, datos = relay.pedir("POST", ruta, cuerpo, headers)
    assert status == 403 and json.loads(datos) == {"error": "esta clave es solo para escuchar"}
    assert not _ordenes_recibidas(ws)                                # la PC no se enteró de nada


def _ordenes_recibidas(ws):
    """Los mensajes que la PC (el control falso) recibió y son órdenes."""
    salida = []
    while True:
        try:
            m = json.loads(ws.recv(timeout=0.3))
        except TimeoutError:
            return salida
        if m.get("tipo") in ("sintonizar", "siguiente", "anterior"):
            salida.append(m)


def test_completa_si_puede(relay):
    ws = pc_en_linea(relay)
    _con_clave(relay, ws, "completa")
    _contestar(ws, "sintonizar")
    status, _, datos = relay.pedir("POST", "/api/sintonizar", {"estacion": "B"}, BEARER_GENERADA)
    assert (status, json.loads(datos)) == (200, {"ok": True})


def test_estado_trae_el_permiso(relay):
    ws = pc_en_linea(relay)
    assert json.loads(relay.pedir("GET", "/api/estado", headers=BEARER)[2])["permiso"] == "completa"
    _con_clave(relay, ws, "escucha")
    e = json.loads(relay.pedir("GET", "/api/estado", headers=BEARER_GENERADA)[2])
    assert e["permiso"] == "escucha" and e["radio"]["estacion"] == "A" and e["en_linea"] is True
    conexion, r = _escuchar(relay, 64, BEARER_GENERADA)
    assert r.status == 200                                            # escuchar sí puede
    conexion.close()


def test_logo_con_clave_de_escucha(relay):
    ws = pc_en_linea(relay, iconos={"A": "v1"})
    _con_clave(relay, ws, "escucha")
    assert relay.pedir("GET", "/api/icono/A?v=v1", headers=BEARER_GENERADA)[0] in (200, 404)


def test_la_maestra_entra_con_la_pc_desconectada(relay):
    status, headers, _ = _entrar(relay)
    assert status == 204
    e = json.loads(relay.pedir("GET", "/api/estado", headers={"Cookie": _cookie(headers)[1]})[2])
    assert e["en_linea"] is False and e["permiso"] == "completa"


def test_pagina_usa_el_permiso(relay):
    cuerpo = relay.pedir("GET", "/")[2]
    assert b"permiso" in cuerpo and b"escucha" in cuerpo
