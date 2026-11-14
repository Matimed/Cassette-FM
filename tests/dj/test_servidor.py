import json
import logging
import random
import socket
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import mutagen
import pytest

from cassette_fm.dj.cola import Cola
from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ
from cassette_fm.dj.guiones import RegistroGuiones
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.produccion import Productor
from cassette_fm.dj.servidor import crear_servidor
from cassette_fm.dj.sintetizador import Sintetizador, fonemizador


def fon_falso(texto, lang):
    return f"<{lang}:{texto}>"


class SintetizadorFalso:
    def __init__(self):
        self.puerta = None
        self.cargado = False

    def sintetizar(self, fonemas, voz, lang, salida, velocidad=None, texto=None):
        if self.puerta is not None:
            assert self.puerta.wait(5)
        salida = Path(salida)
        salida.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(salida), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
            w.writeframes(b"\x01\x00" * 4000)
        return 0.5

    def voces(self):
        return ["am_michael", "em_santa"]


def pedido_json(id_="p1", **cambios):
    d = {"id": id_, "estacion": "Lentos", "idioma": "es", "voz": "em_santa", "momento": "2026-11-13T21:47:00-03:00",
         "anterior": {"artista": "Whitesnake", "titulo": "Is This Love"},
         "siguiente": {"artista": "Foreigner", "titulo": "Waiting for a Girl Like You"}}
    d.update(cambios)
    return d


class Servicio:
    pass


def montar(tmp_path, sintetizador, fonemizar=fon_falso, lexico=None, cola=None, modelos_dir=None, config=None,
           timeout=10.0, modo=None, probar_llm=None, llm=None, hechos=None, reloj=None):
    s = Servicio()
    s.rutas = RutasDJ(config=tmp_path / "cfg" / "config.toml", estado=tmp_path / "estado", clips=tmp_path / "clips")
    s.config = config or ConfigServicioDJ(modelos_dir=modelos_dir or tmp_path / "sin-modelos")
    s.guiones = RegistroGuiones(s.rutas.guiones)
    s.sint = sintetizador
    s.productor = Productor(s.config, s.rutas, sintetizador, fonemizar, lexico or Lexico(), s.guiones,
                            azar=random.Random(1), modo=modo, llm=llm, hechos=hechos,
                            **({"reloj": reloj} if reloj else {}))
    s.cola = cola or Cola(s.productor, trabajadores=1)
    s.srv = crear_servidor(s.cola, sintetizador, "127.0.0.1", 0, s.config.modelos_dir, timeout=timeout,
                           modo=modo, probar_llm=probar_llm)
    threading.Thread(target=lambda: s.srv.serve_forever(poll_interval=0.02), daemon=True).start()
    s.base = f"http://127.0.0.1:{s.srv.server_address[1]}"
    return s


@pytest.fixture
def servicio(tmp_path):
    creados = []

    def crear(*args, **kw):
        s = montar(tmp_path, *args, **kw)
        creados.append(s)
        return s

    yield crear
    for s in creados:
        s.srv.shutdown()
        s.srv.server_close()
        s.cola.detener(2)


def pedir(s, metodo, ruta, cuerpo=None, crudo=None):
    datos = crudo if crudo is not None else (json.dumps(cuerpo).encode() if cuerpo is not None else None)
    req = urllib.request.Request(s.base + ruta, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def json_de(respuesta):
    codigo, cuerpo, _ = respuesta
    return codigo, json.loads(cuerpo)


def esperar_estado(s, id_, estados=("listo", "error", "cancelado"), timeout=5.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        codigo, d = json_de(pedir(s, "GET", f"/intervenciones/{id_}"))
        if codigo == 200 and d["estado"] in estados:
            return d
        time.sleep(0.02)
    raise AssertionError("el trabajo no terminó")


def test_post_y_consulta_hasta_listo_y_descarga_del_audio(servicio):
    s = servicio(SintetizadorFalso())
    assert json_de(pedir(s, "POST", "/intervenciones", pedido_json())) == (202, {"id": "p1"})
    d = esperar_estado(s, "p1")
    assert d["estado"] == "listo" and d["duracion"] == 0.5 and d["texto"] and "cancion" in d["ingredientes"]
    codigo, cuerpo, cabeceras = pedir(s, "GET", "/intervenciones/p1/audio")
    assert codigo == 200 and cabeceras["Content-Type"] == "audio/wav" and cuerpo[:4] == b"RIFF"
    (s.rutas.clips / "copia.wav").write_bytes(cuerpo)
    assert mutagen.File(s.rutas.clips / "copia.wav").info.length > 0


def test_post_es_idempotente(servicio):
    s = servicio(SintetizadorFalso())
    pedir(s, "POST", "/intervenciones", pedido_json())
    assert json_de(pedir(s, "POST", "/intervenciones", pedido_json()))[0] == 202
    esperar_estado(s, "p1")
    assert len(s.guiones.ultimos(10)) == 1


@pytest.mark.parametrize("cambios,campo", [
    ({"estacion": None}, "estacion"), ({"idioma": "fr"}, "idioma"), ({"momento": "2026-11-13T21:47:00"}, "momento"),
    ({"id": "../x"}, "id"), ({"siguiente": "texto"}, "siguiente"),
])
def test_pedido_invalido_da_400_con_el_campo(servicio, cambios, campo):
    s = servicio(SintetizadorFalso())
    codigo, d = json_de(pedir(s, "POST", "/intervenciones", pedido_json(**cambios)))
    assert codigo == 400 and campo in d["error"]
    assert not s.rutas.clips.exists() or not list(s.rutas.clips.glob("*"))


def test_json_roto_o_no_objeto_da_400(servicio):
    s = servicio(SintetizadorFalso())
    assert json_de(pedir(s, "POST", "/intervenciones", crudo=b"{no es json"))[0] == 400
    assert json_de(pedir(s, "POST", "/intervenciones", crudo=b"[1, 2]"))[0] == 400
    assert json_de(pedir(s, "POST", "/intervenciones", crudo=b""))[0] == 400


def test_cuerpo_demasiado_grande_413(servicio):
    s = servicio(SintetizadorFalso())
    codigo, d = json_de(pedir(s, "POST", "/intervenciones", crudo=b"x" * 70_000))
    assert codigo == 413 and "error" in d


def test_estado_y_audio_de_id_desconocido_404(servicio):
    s = servicio(SintetizadorFalso())
    assert pedir(s, "GET", "/intervenciones/nadie")[0] == 404
    assert pedir(s, "GET", "/intervenciones/nadie/audio")[0] == 404
    assert pedir(s, "DELETE", "/intervenciones/nadie")[0] == 404


def test_audio_de_un_trabajo_no_listo_409(servicio):
    sint = SintetizadorFalso()
    sint.puerta = threading.Event()
    s = servicio(sint)
    pedir(s, "POST", "/intervenciones", pedido_json())
    esperar_estado(s, "p1", estados=("trabajando",))
    codigo, d = json_de(pedir(s, "GET", "/intervenciones/p1/audio"))
    assert codigo == 409 and "todavía no está listo" in d["error"]
    sint.puerta.set()


def test_delete_cancela_un_pendiente_y_no_uno_en_trabajo(servicio):
    sint = SintetizadorFalso()
    sint.puerta = threading.Event()
    s = servicio(sint)
    pedir(s, "POST", "/intervenciones", pedido_json("a"))
    esperar_estado(s, "a", estados=("trabajando",))
    pedir(s, "POST", "/intervenciones", pedido_json("b"))
    assert json_de(pedir(s, "DELETE", "/intervenciones/b")) == (200, {"cancelado": True})
    assert json_de(pedir(s, "DELETE", "/intervenciones/a")) == (200, {"cancelado": False})
    assert esperar_estado(s, "b")["estado"] == "cancelado"
    sint.puerta.set()


def test_voces(servicio):
    s = servicio(SintetizadorFalso())
    assert json_de(pedir(s, "GET", "/voces")) == (200, {"voces": ["am_michael", "em_santa"]})


def test_voces_sin_modelos_da_503_claro(servicio, tmp_path):
    s = servicio(Sintetizador(ConfigServicioDJ(modelos_dir=tmp_path / "vacio")), modelos_dir=tmp_path / "vacio")
    codigo, d = json_de(pedir(s, "GET", "/voces"))
    assert codigo == 503 and "cassette-dj modelos" in d["error"]


def test_salud_informa_modelos_faltantes_y_contadores(servicio, tmp_path):
    s = servicio(SintetizadorFalso(), modelos_dir=tmp_path / "vacio")
    codigo, d = json_de(pedir(s, "GET", "/salud"))
    assert codigo == 200 and d["ok"] is True and d["modelo_cargado"] is False
    assert d["faltan_modelos"] == ["kokoro-v1.0.onnx", "voices-v1.0.bin"]
    assert d["trabajos"] == {"pendiente": 0, "trabajando": 0, "listo": 0, "error": 0, "cancelado": 0}


def test_un_pedido_sin_modelos_termina_en_error_claro(servicio, tmp_path):
    cfg = ConfigServicioDJ(modelos_dir=tmp_path / "vacio")
    s = servicio(Sintetizador(cfg), config=cfg)
    pedir(s, "POST", "/intervenciones", pedido_json())
    d = esperar_estado(s, "p1")
    assert d["estado"] == "error" and "cassette-dj modelos" in d["error"]


def test_id_con_caracteres_raros_en_la_url_da_404(servicio):
    s = servicio(SintetizadorFalso())
    assert pedir(s, "GET", "/intervenciones/..%2F..%2Fetc%2Fpasswd")[0] == 404
    assert pedir(s, "GET", "/intervenciones/a%20b/audio")[0] == 404


def test_ruta_desconocida_404(servicio):
    s = servicio(SintetizadorFalso())
    assert pedir(s, "GET", "/nada")[0] == 404
    assert pedir(s, "POST", "/nada", {})[0] == 404
    assert pedir(s, "DELETE", "/nada")[0] == 404


def test_error_inesperado_500_y_se_loguea(servicio, caplog):
    class ColaRota:
        def estado(self, id_):
            raise RuntimeError("falla interna rara")

        def contadores(self):
            return {}

        def detener(self, espera=5.0):
            pass

    caplog.set_level(logging.ERROR, logger="cassette_fm")
    s = servicio(SintetizadorFalso(), cola=ColaRota())
    codigo, d = json_de(pedir(s, "GET", "/intervenciones/x"))
    assert codigo == 500 and "falla interna rara" not in d["error"]
    assert "falla interna rara" in caplog.text


def crudo(s, texto: bytes, esperar_cierre=True, lectura=4.0) -> bytes:
    """Habla HTTP a mano: manda `texto` tal cual y devuelve lo que conteste el servidor."""
    with socket.create_connection(("127.0.0.1", s.srv.server_address[1]), timeout=lectura) as c:
        c.sendall(texto)
        trozos = []
        while True:
            try:
                dato = c.recv(65536)
            except (TimeoutError, ConnectionResetError):
                break
            if not dato:
                break
            trozos.append(dato)
        return b"".join(trozos)


@pytest.mark.parametrize("largo", ["-1", "abc", "1e3", " ", "99999999999999999999"])
def test_content_length_invalido_da_400_o_413(servicio, largo):
    s = servicio(SintetizadorFalso())
    r = crudo(s, f"POST /intervenciones HTTP/1.0\r\nContent-Length: {largo}\r\n\r\n{{}}".encode())
    assert r.split(b" ")[1] in (b"400", b"413"), r[:80]


def test_cuerpo_incompleto_da_408_y_no_cuelga_el_hilo(servicio):
    s = servicio(SintetizadorFalso(), timeout=0.5)
    t0 = time.monotonic()
    r = crudo(s, b"POST /intervenciones HTTP/1.0\r\nContent-Length: 100\r\n\r\n{}")   # promete 100 bytes, manda 2
    assert r.split(b" ")[1] == b"408", r[:80]
    assert time.monotonic() - t0 < 3.0


def test_json_muy_anidado_da_400(servicio):
    s = servicio(SintetizadorFalso())
    cuerpo = b"[" * 30000 + b"]" * 30000
    r = crudo(s, b"POST /intervenciones HTTP/1.0\r\nContent-Length: %d\r\n\r\n" % len(cuerpo) + cuerpo)
    assert r.split(b" ")[1] == b"400", r[:80]


def test_un_host_que_no_es_local_avisa_que_no_hay_autenticacion(servicio, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="cassette_fm")
    s = servicio(SintetizadorFalso())
    srv = crear_servidor(s.cola, s.sint, "0.0.0.0", 0, tmp_path)
    srv.server_close()
    assert "sin autenticación" in caplog.text
    caplog.clear()
    srv = crear_servidor(s.cola, s.sint, "127.0.0.1", 0, tmp_path)
    srv.server_close()
    assert "sin autenticación" not in caplog.text


def test_de_punta_a_punta_con_kokoro_real(servicio, modelos_reales):
    pytest.importorskip("kokoro_onnx")
    cfg = ConfigServicioDJ(modelos_dir=modelos_reales)
    sint = Sintetizador(cfg)
    s = servicio(sint, fonemizar=fonemizador(), lexico=Lexico({"Daddy Yankee": "en-us"}), config=cfg)
    pedir(s, "POST", "/intervenciones",
          pedido_json("es1", siguiente={"artista": "Daddy Yankee", "titulo": "Gasolina"}))
    d = esperar_estado(s, "es1", timeout=60)
    assert d["estado"] == "listo", d
    codigo, audio, _ = pedir(s, "GET", "/intervenciones/es1/audio")
    (s.rutas.clips / "es1-copia.wav").write_bytes(audio)
    assert 3.0 <= mutagen.File(s.rutas.clips / "es1-copia.wav").info.length <= 15.0
    guion = [g for g in s.guiones.ultimos(10) if g["id"] == "es1"][-1]
    assert guion["texto"] and "{" in guion["marcado"]
    if "Daddy Yankee" in guion["marcado"]:
        assert "{en-us:Daddy Yankee}" in guion["marcado"] and "æ" in guion["fonemas"]
    assert "θ" not in guion["fonemas"]            # español con "s" argentina (el inglés no tiene θ en estos textos)
    pedir(s, "POST", "/intervenciones", pedido_json("en1", idioma="en", voz="am_michael"))
    d = esperar_estado(s, "en1", timeout=60)
    assert d["estado"] == "listo", d


def test_servicio_con_hechos_falsos_de_punta_a_punta(servicio, servidor_http):
    """El servicio arma clima + MusicBrainz y los usa; con los servidores caídos igual hay frase."""
    from cassette_fm.dj.config import ConfigServicioDJ
    from cassette_fm.dj.hechos import FuenteHechos
    from cassette_fm.dj.hechos.cache import CacheHechos
    from cassette_fm.dj.hechos.clima import ClienteClima
    from cassette_fm.dj.hechos.musicbrainz import ClienteMusicBrainz

    aha = "7364dea6-0000-4000-8000-000000000001"
    servidor_http.responder("/v1/forecast", {"current": {"temperature_2m": 22.0, "weather_code": 3, "is_day": 1}})
    servidor_http.responder("/ws/2/release-group", {"release-groups": []})
    servidor_http.responder("/ws/2/recording", {"recordings": [{
        "id": "r1", "title": "Waiting for a Girl Like You", "first-release-date": "1981-09-02",
        "artist-credit": [{"name": "Foreigner", "artist": {"id": aha, "name": "Foreigner"}}]}]})
    servidor_http.responder(f"/ws/2/artist/{aha}", {"id": aha, "name": "Foreigner", "type": "Group", "country": "GB", "life-span": {"begin": "1976"}})
    cfg = ConfigServicioDJ(contacto="t@example.com", open_meteo_url=servidor_http.url + "/v1/forecast",
                           musicbrainz_url=servidor_http.url + "/ws/2", timeout_hechos_segundos=1.0,
                           pesos_ingredientes={"estacion": 0.0, "hora": 0.0, "momento": 0.0, "album": 0.0,
                                               "anterior": 0.0, "clima": 1.0, "dato": 1.0}, ingredientes_max=3)
    cache = CacheHechos(None)
    fuente = FuenteHechos(ClienteClima(cfg, cache), ClienteMusicBrainz(cfg, cache, dormir=lambda s: None), 3)
    s = servicio(SintetizadorFalso(), config=cfg)
    s.productor._hechos = fuente
    codigo, d = json_de(pedir(s, "POST", "/intervenciones", pedido_json("hr1")))
    assert codigo == 202
    listo = esperar_estado(s, "hr1", timeout=8)
    assert listo["estado"] == "listo" and {"clima", "dato"} <= set(listo["ingredientes"])
    guion = s.guiones.ultimos(1)[0]
    assert guion["hechos"]["musicbrainz"]["anio"] == 1981 and guion["hechos"]["clima"]["temperatura"] == 22
    # servicios de hechos caídos: la frase sale igual, sin clima ni dato
    servidor_http.reglas.clear()
    codigo, _ = json_de(pedir(s, "POST", "/intervenciones", pedido_json("hr2", recientes=[])))
    listo = esperar_estado(s, "hr2", timeout=8)
    assert listo["estado"] == "listo" and listo["texto"]


# --- modo plantillas / llm ---

_MOMENTO_PRUEBA = __import__("datetime").datetime.fromisoformat("2026-11-13T21:47:00-03:00").timestamp()

def test_get_modo(servicio):
    from cassette_fm.dj.modo import ModoDJ
    s = servicio(SintetizadorFalso(), modo=ModoDJ())
    assert json_de(pedir(s, "GET", "/modo")) == (200, {"modo": "plantillas"})
    s2 = servicio(SintetizadorFalso())              # sin modo: siempre plantillas
    assert json_de(pedir(s2, "GET", "/modo")) == (200, {"modo": "plantillas"})


def test_post_modo_cambia_y_se_refleja_en_salud(servicio):
    from cassette_fm.dj.modo import ModoDJ
    modo = ModoDJ()
    s = servicio(SintetizadorFalso(), modo=modo, probar_llm=lambda: True)
    assert json_de(pedir(s, "POST", "/modo", {"modo": "llm"})) == (200, {"modo": "llm", "llm": "ok"})
    assert modo.actual() == "llm" and json_de(pedir(s, "GET", "/modo"))[1] == {"modo": "llm"}
    assert json_de(pedir(s, "GET", "/salud"))[1]["modo"] == "llm"


def test_post_modo_llm_informa_si_el_llm_responde(servicio):
    from cassette_fm.dj.modo import ModoDJ
    s = servicio(SintetizadorFalso(), modo=ModoDJ(), probar_llm=lambda: False)
    assert json_de(pedir(s, "POST", "/modo", {"modo": "llm"}))[1] == {"modo": "llm", "llm": "no responde"}


def test_post_modo_plantillas_no_prueba_el_llm(servicio):
    from cassette_fm.dj.modo import ModoDJ
    llamadas = []
    s = servicio(SintetizadorFalso(), modo=ModoDJ("llm"), probar_llm=lambda: llamadas.append(1) or True)
    assert json_de(pedir(s, "POST", "/modo", {"modo": "plantillas"})) == (200, {"modo": "plantillas"})
    assert llamadas == []


@pytest.mark.parametrize("cuerpo", [{}, {"modo": "otro"}, {"modo": 3}, {"modo": None}, [1], "x"])
def test_post_modo_invalido_400(servicio, cuerpo):
    from cassette_fm.dj.modo import ModoDJ
    modo = ModoDJ()
    s = servicio(SintetizadorFalso(), modo=modo)
    codigo, d = json_de(pedir(s, "POST", "/modo", cuerpo))
    assert codigo == 400 and "modo" in d["error"] and modo.actual() == "plantillas"


def test_post_modo_con_json_roto_400(servicio):
    s = servicio(SintetizadorFalso())
    assert json_de(pedir(s, "POST", "/modo", crudo=b"{no es json"))[0] == 400


def test_de_punta_a_punta_en_modo_llm_con_servidores_falsos(servicio, servidor_http, llm_falso):
    from cassette_fm.dj.hechos import FuenteHechos
    from cassette_fm.dj.hechos.cache import CacheHechos
    from cassette_fm.dj.hechos.musicbrainz import ClienteMusicBrainz
    from cassette_fm.dj.hechos.wikipedia import ClienteWikipedia
    from cassette_fm.dj.llm import ClienteLLM
    from cassette_fm.dj.modo import ModoDJ

    aha = "7364dea6-0000-4000-8000-000000000001"
    servidor_http.responder("/ws/2/release-group", {"release-groups": []})
    servidor_http.responder("/ws/2/recording", {"recordings": [{
        "id": "r1", "title": "Waiting for a Girl Like You", "first-release-date": "1981-09-02",
        "artist-credit": [{"name": "Foreigner", "artist": {"id": aha, "name": "Foreigner"}}]}]})
    servidor_http.responder(f"/ws/2/artist/{aha}", {"id": aha, "name": "Foreigner", "type": "Group", "country": "GB",
                                                    "life-span": {"begin": "1976"},
                                                    "relations": [{"type": "wikidata", "url": {
                                                        "resource": "https://www.wikidata.org/wiki/Q156305"}}]})
    servidor_http.responder("/w", {"entities": {"Q156305": {"sitelinks": {"eswiki": {"title": "Foreigner"}}}}})
    servidor_http.responder("/es/api/rest_v1/page/summary/Foreigner", {
        "type": "standard", "title": "Foreigner", "extract": "Foreigner es una banda de rock formada en Nueva York.",
        "content_urls": {"desktop": {"page": "https://es.wikipedia.org/wiki/Foreigner"}}})
    llm_falso.respuestas = ["Ahora suena Waiting for a Girl Like You de Foreigner, una banda formada en Nueva York."]
    cfg = ConfigServicioDJ(contacto="t@example.com", musicbrainz_url=servidor_http.url + "/ws/2",
                           wikidata_url=servidor_http.url + "/w", wikipedia_url=servidor_http.url + "/{idioma}",
                           llm_url=llm_falso.url, timeout_hechos_segundos=1.0, llm_timeout_segundos=5.0,
                           pesos_ingredientes={"estacion": 0.0, "hora": 0.0, "momento": 0.0, "album": 0.0,
                                               "anterior": 0.0, "clima": 0.0, "dato": 1.0}, ingredientes_max=2)
    cache = CacheHechos(None)
    fuente = FuenteHechos(None, ClienteMusicBrainz(cfg, cache, dormir=lambda s: None), 3,
                          wikipedia=ClienteWikipedia(cfg, cache))
    modo = ModoDJ()
    llm = ClienteLLM(cfg)
    s = servicio(SintetizadorFalso(), config=cfg, modo=modo, probar_llm=llm.disponible, llm=llm, hechos=fuente,
                 reloj=lambda: _MOMENTO_PRUEBA - 600)
    assert json_de(pedir(s, "POST", "/modo", {"modo": "llm"})) == (200, {"modo": "llm", "llm": "ok"})
    assert json_de(pedir(s, "POST", "/intervenciones", pedido_json("llm1")))[0] == 202
    listo = esperar_estado(s, "llm1", timeout=10)
    assert listo["estado"] == "listo" and "Nueva York" in listo["texto"] and "dato" in listo["ingredientes"]
    guion = s.guiones.ultimos(1)[0]
    assert guion["fuente"] == "llm" and guion["hechos"]["wikipedia"]["url"] == "https://es.wikipedia.org/wiki/Foreigner"
    assert "Nueva York" in llm_falso.pedidos[0]["messages"][1]["content"]
    # vuelta a plantillas: ni el LLM ni Wikipedia reciben pedidos nuevos
    pedidos_llm, pedidos_http = len(llm_falso.pedidos), len(servidor_http.pedidos)
    # cachés nuevas: si en plantillas se pidiera Wikipedia, se vería en los pedidos al servidor
    cache2 = CacheHechos(None)
    s.productor._hechos = FuenteHechos(None, ClienteMusicBrainz(cfg, cache2, dormir=lambda s: None), 3,
                                       wikipedia=ClienteWikipedia(cfg, cache2))
    assert json_de(pedir(s, "POST", "/modo", {"modo": "plantillas"})) == (200, {"modo": "plantillas"})
    assert json_de(pedir(s, "POST", "/intervenciones", pedido_json("llm2")))[0] == 202
    assert esperar_estado(s, "llm2", timeout=10)["estado"] == "listo"
    assert len(llm_falso.pedidos) == pedidos_llm and s.guiones.ultimos(1)[0]["fuente"] == "plantilla"
    assert not any("/w?" in r or "summary" in r for r, _ in servidor_http.pedidos[pedidos_http:])


def test_en_modo_llm_con_el_llm_caido_igual_hay_frase(servicio, llm_falso):
    from cassette_fm.dj.llm import ClienteLLM
    from cassette_fm.dj.modo import ModoDJ
    llm_falso.codigo = 503
    llm_falso.cuerpo_crudo = "ocupado"
    cfg = ConfigServicioDJ(llm_url=llm_falso.url, llm_timeout_segundos=2.0)
    s = servicio(SintetizadorFalso(), config=cfg, modo=ModoDJ("llm"), llm=ClienteLLM(cfg),
                 reloj=lambda: _MOMENTO_PRUEBA - 600)
    assert json_de(pedir(s, "POST", "/intervenciones", pedido_json("llm3")))[0] == 202
    listo = esperar_estado(s, "llm3", timeout=10)
    assert listo["estado"] == "listo" and listo["texto"]
    assert s.guiones.ultimos(1)[0]["fuente"] == "plantilla" and "503" in s.guiones.ultimos(1)[0]["motivo"]


def test_post_modo_llm_distingue_que_falte_el_modelo(servicio):
    from cassette_fm.dj.modo import ModoDJ
    s = servicio(SintetizadorFalso(), modo=ModoDJ(), probar_llm=lambda: "falta el modelo")
    assert json_de(pedir(s, "POST", "/modo", {"modo": "llm"}))[1] == {"modo": "llm", "llm": "falta el modelo"}
