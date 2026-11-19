import json
import threading
import time
import urllib.parse

import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus

from ayudas_relay import CASA, OYENTES, TOKEN, casa, esperar, estado, pc_en_linea, recibir_tipo

HOLA = json.dumps({"tipo": "hola", "protocolo": 1, "calidades": [64, 96, 160]})
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _casa(relay):
    return relay.app[CASA]


def _icono_url(nombre, v="v1"):
    return f"/casa/icono/{urllib.parse.quote(nombre, safe='')}?v={v}"


def _subir(relay, nombre, datos=PNG, tipo="image/png", v="v1", token=TOKEN):
    headers = {"Content-Type": tipo}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return relay.pedir("PUT", _icono_url(nombre, v), datos, headers)[0]


def test_salud_sin_clave(relay):
    status, _, cuerpo = relay.pedir("GET", "/salud")
    assert status == 200 and cuerpo == b"ok"


@pytest.mark.parametrize("token", [None, "otra-clave"])
def test_control_sin_clave_401(relay, token):
    with pytest.raises(InvalidStatus) as e:
        casa(relay, token=token)
    assert e.value.response.status_code == 401


def test_audio_e_icono_sin_clave_401(relay):
    with pytest.raises(InvalidStatus) as e:
        casa(relay, "/casa/audio?calidad=96", token="otra")
    assert e.value.response.status_code == 401
    pc_en_linea(relay)
    assert _subir(relay, "A", token=None) == 401
    assert _subir(relay, "A", token="otra") == 401


def test_hola_contesta_demanda(relay):
    ws = casa(relay)
    ws.send(HOLA)
    assert recibir_tipo(ws, "demanda") == {"tipo": "demanda", "calidades": []}


def test_protocolo_desconocido_cierra(relay):
    ws = casa(relay)
    ws.send(json.dumps({"tipo": "hola", "protocolo": 2, "calidades": [96]}))
    with pytest.raises(ConnectionClosed):
        ws.recv(timeout=2)
    assert not relay.en_loop(lambda: _casa(relay).en_linea)


def test_en_linea_y_visto_hace(relay):
    c = _casa(relay)
    assert relay.en_loop(lambda: (c.en_linea, c.visto_hace(), c.radio())) == (False, None, None)
    ws = pc_en_linea(relay)
    assert relay.en_loop(lambda: (c.en_linea, c.visto_hace())) == (True, None)
    ws.close()
    assert esperar(lambda: not relay.en_loop(lambda: c.en_linea))
    visto = relay.en_loop(lambda: c.visto_hace())
    assert isinstance(visto, int) and visto >= 0
    assert relay.en_loop(lambda: c.radio())["estacion"] == "A"


def test_guarda_estado_y_descarta_seq_viejo(relay):
    ws = pc_en_linea(relay)
    ws.send(json.dumps(estado(seq=2, estacion="B")))
    ws.send(json.dumps(estado(seq=1, estacion="A")))
    ws.send(json.dumps(estado(seq="3", estacion="A")))
    time.sleep(0.2)
    radio = relay.en_loop(lambda: _casa(relay).radio())
    assert radio["estacion"] == "B" and "tipo" not in radio and "seq" not in radio
    assert radio["pista"] == "Artista - Tema" and radio["segundo"] == 12.5


def test_seq_vuelve_a_empezar_al_reconectar(relay):
    ws = pc_en_linea(relay)
    ws.send(json.dumps(estado(seq=5, estacion="B")))
    time.sleep(0.1)
    ws.close()
    ws2 = casa(relay)
    ws2.send(HOLA)
    ws2.send(json.dumps(estado(seq=1, estacion="a/b?c")))
    assert esperar(lambda: relay.en_loop(lambda: _casa(relay).radio()["estacion"]) == "a/b?c")


def test_tipo_desconocido_json_roto_y_latido(relay, caplog):
    ws = pc_en_linea(relay)
    ws.send("{roto")
    ws.send(json.dumps({"tipo": "algo-nuevo"}))
    ws.send(json.dumps({"tipo": "latido"}))
    ws.send(b"binario en el control")
    ws.send(json.dumps(estado(seq=2, estacion="B")))
    assert esperar(lambda: relay.en_loop(lambda: _casa(relay).radio()["estacion"]) == "B")
    assert "algo-nuevo" in caplog.text


def test_pide_cada_logo_una_vez(relay):
    ws = pc_en_linea(relay, iconos={"Más Gasolina F.M.": "v1"})
    assert recibir_tipo(ws, "pedir_icono") == {"tipo": "pedir_icono", "estacion": "Más Gasolina F.M."}
    ws.send(json.dumps(estado(seq=2, iconos={"Más Gasolina F.M.": "v1"})))
    with pytest.raises(AssertionError):
        recibir_tipo(ws, "pedir_icono", timeout=0.3)


def test_logo_pendiente_vence_y_se_repide(relay):
    ws = pc_en_linea(relay, iconos={"A": "v1"})
    recibir_tipo(ws, "pedir_icono")
    time.sleep(0.6)
    ws.send(json.dumps(estado(seq=2, iconos={"A": "v1"})))
    assert recibir_tipo(ws, "pedir_icono")["estacion"] == "A"


def test_logo_se_repide_al_reconectar(relay):
    ws = pc_en_linea(relay, iconos={"A": "v1"})
    recibir_tipo(ws, "pedir_icono")
    ws.close()
    ws2 = pc_en_linea(relay, iconos={"A": "v1"})
    assert recibir_tipo(ws2, "pedir_icono")["estacion"] == "A"


def test_subir_logo(relay):
    nombre = "Más Gasolina F.M."
    ws = pc_en_linea(relay, iconos={nombre: "v1"})
    recibir_tipo(ws, "pedir_icono")
    assert _subir(relay, nombre) == 204
    assert relay.en_loop(lambda: _casa(relay).icono(nombre)) == ("v1", "image/png", PNG)
    ws.send(json.dumps(estado(seq=2, iconos={nombre: "v1"})))
    with pytest.raises(AssertionError):
        recibir_tipo(ws, "pedir_icono", timeout=0.3)


def test_subir_logo_con_barra_y_signo(relay):
    pc_en_linea(relay, iconos={"a/b?c": "v1"})
    assert _subir(relay, "a/b?c") == 204
    assert relay.en_loop(lambda: _casa(relay).icono("a/b?c"))[2] == PNG


def test_logo_rechazado(relay):
    pc_en_linea(relay, iconos={"A": "v1"})
    assert _subir(relay, "Z") == 400
    assert _subir(relay, "A", tipo="image/svg+xml") == 415
    assert _subir(relay, "A", datos=b"x" * (4 * 1024 * 1024 + 1)) == 413
    assert _subir(relay, "A", datos=b"") == 400
    assert relay.en_loop(lambda: _casa(relay).icono("A")) is None


def test_logos_de_emisoras_que_ya_no_estan_se_borran(relay):
    ws = pc_en_linea(relay, iconos={"A": "v1", "B": "v1"})
    assert _subir(relay, "A") == 204
    ws.send(json.dumps(estado(seq=2, iconos={"B": "v1"})))
    assert esperar(lambda: relay.en_loop(lambda: _casa(relay).icono("A")) is None)


def _contestar(ws, ok=True, error=None, tipo="sintonizar", recibidos=None):
    def hilo():
        m = recibir_tipo(ws, tipo)
        if recibidos is not None:
            recibidos.append(m)
        r = {"tipo": "resultado", "id": m["id"], "ok": ok}
        if error:
            r["error"] = error
        ws.send(json.dumps(r))
    t = threading.Thread(target=hilo, daemon=True)
    t.start()
    return t


def test_orden_ok_y_error(relay):
    ws = pc_en_linea(relay)
    recibidos = []
    _contestar(ws, recibidos=recibidos)
    assert relay.en_loop(lambda: _casa(relay).orden("sintonizar", estacion="a/b?c")) == (200, {"ok": True})
    assert recibidos[0]["estacion"] == "a/b?c" and recibidos[0]["id"]
    _contestar(ws, ok=False, error="esa emisora no existe")
    assert relay.en_loop(lambda: _casa(relay).orden("sintonizar", estacion="Z")) == (
        409, {"error": "esa emisora no existe"})
    _contestar(ws, tipo="siguiente")
    assert relay.en_loop(lambda: _casa(relay).orden("siguiente")) == (200, {"ok": True})


def test_orden_fuera_de_linea(relay):
    assert relay.en_loop(lambda: _casa(relay).orden("siguiente")) == (503, {"error": "la radio está fuera de línea"})


def test_orden_sin_respuesta(relay):
    pc_en_linea(relay)
    inicio = time.monotonic()
    status, cuerpo = relay.en_loop(lambda: _casa(relay).orden("siguiente"))
    assert status == 504 and "error" in cuerpo and 0.9 < time.monotonic() - inicio < 2


def test_orden_pendiente_y_control_caido(relay):
    ws = pc_en_linea(relay)

    def cortar():
        recibir_tipo(ws, "anterior")
        ws.close()
    threading.Thread(target=cortar, daemon=True).start()
    inicio = time.monotonic()
    assert relay.en_loop(lambda: _casa(relay).orden("anterior")) == (503, {"error": "la radio se desconectó"})
    assert time.monotonic() - inicio < 0.8


def test_control_nuevo_reemplaza(relay):
    ws = pc_en_linea(relay)
    ws2 = pc_en_linea(relay)
    with pytest.raises(ConnectionClosed):
        while True:
            ws.recv(timeout=2)
    assert relay.en_loop(lambda: _casa(relay).en_linea)
    _contestar(ws2, tipo="siguiente")
    assert relay.en_loop(lambda: _casa(relay).orden("siguiente")) == (200, {"ok": True})


@pytest.mark.parametrize("calidad", ["128", "abc", ""])
def test_audio_calidad_invalida(relay, calidad):
    ws = casa(relay, f"/casa/audio?calidad={calidad}")
    with pytest.raises(ConnectionClosed) as e:
        ws.recv(timeout=2)
    assert e.value.rcvd.code == 1008


def test_audio_reparte_a_los_oyentes(relay):
    oyente = relay.en_loop(lambda: relay.app[OYENTES].agregar(96))
    audio = casa(relay, "/casa/audio?calidad=96")
    audio.send(b"mp3")
    assert relay.en_loop(lambda: oyente.tomar(2)) == b"mp3"


def test_audio_nuevo_reemplaza(relay):
    oyente = relay.en_loop(lambda: relay.app[OYENTES].agregar(96))
    viejo = casa(relay, "/casa/audio?calidad=96")
    nuevo = casa(relay, "/casa/audio?calidad=96")
    with pytest.raises(ConnectionClosed):
        while True:
            viejo.recv(timeout=2)
    nuevo.send(b"nuevo")
    assert relay.en_loop(lambda: oyente.tomar(2)) == b"nuevo"


def test_demanda_al_primer_oyente_y_al_vencer_la_gracia(relay):
    ws = pc_en_linea(relay)
    oyentes = relay.app[OYENTES]
    oyente = relay.en_loop(lambda: oyentes.agregar(64))
    assert recibir_tipo(ws, "demanda") == {"tipo": "demanda", "calidades": [64]}
    relay.en_loop(lambda: oyentes.quitar(oyente))
    inicio = time.monotonic()
    assert recibir_tipo(ws, "demanda") == {"tipo": "demanda", "calidades": []}
    assert time.monotonic() - inicio >= 0.15


def test_hola_trae_la_demanda_vigente(relay):
    relay.en_loop(lambda: relay.app[OYENTES].agregar(160))
    ws = casa(relay)
    ws.send(HOLA)
    assert recibir_tipo(ws, "demanda") == {"tipo": "demanda", "calidades": [160]}


# --- claves ---

from ayudas_relay import ACCESO, CLAVE  # noqa: E402
from cassette_relay.acceso import Identidad, huella  # noqa: E402

GENERADA = "k7qm-abcd-2345-6789"


def _lista(permiso="escucha", ident="abcd1234"):
    return [{"id": ident, "permiso": permiso, "huella": huella(GENERADA)}]


def _mandar_claves(ws, claves):
    ws.send(json.dumps({"tipo": "claves", "claves": claves}))


def _probar(relay, clave):
    return relay.en_loop(lambda: relay.app[ACCESO].probar(clave))


def test_claves_validas_las_conoce_el_acceso(relay):
    ws = pc_en_linea(relay)
    assert _probar(relay, GENERADA)[0] == "mal"
    _mandar_claves(ws, _lista())
    assert esperar(lambda: _probar(relay, GENERADA) == ("ok", Identidad("abcd1234", "escucha")))


@pytest.mark.parametrize("invalida", [
    "no es lista", 3, None, [{"id": "abcd1234", "permiso": "escucha", "huella": "corta"}],
    [{"id": "abcd1234", "permiso": "escucha", "huella": "a" * 64}] * 2,
    [{"id": f"{i:08x}", "permiso": "escucha", "huella": "a" * 64} for i in range(201)],
])
def test_claves_invalidas_no_desarman_la_lista_vigente(relay, invalida, caplog):
    ws = pc_en_linea(relay)
    _mandar_claves(ws, _lista())
    assert esperar(lambda: _probar(relay, GENERADA)[0] == "ok")
    _mandar_claves(ws, invalida)
    ws.send(json.dumps(estado(seq=2)))                    # el control sigue andando y ya procesó lo anterior
    assert esperar(lambda: relay.en_loop(lambda: _casa(relay).radio())["estacion"] == "A" and "inválida" in caplog.text)
    assert _probar(relay, GENERADA)[0] == "ok"


def test_log_sin_huellas_ni_claves(relay, caplog):
    ws = pc_en_linea(relay)
    _mandar_claves(ws, _lista())
    assert esperar(lambda: _probar(relay, GENERADA)[0] == "ok")
    assert huella(GENERADA) not in caplog.text and GENERADA not in caplog.text
