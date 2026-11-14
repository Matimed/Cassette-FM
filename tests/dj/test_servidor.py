import json
import logging
import random
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

    def sintetizar(self, fonemas, voz, lang, salida):
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


def montar(tmp_path, sintetizador, fonemizar=fon_falso, lexico=None, cola=None, modelos_dir=None, config=None):
    s = Servicio()
    s.rutas = RutasDJ(config=tmp_path / "cfg" / "config.toml", estado=tmp_path / "estado", clips=tmp_path / "clips")
    s.config = config or ConfigServicioDJ(modelos_dir=modelos_dir or tmp_path / "sin-modelos")
    s.guiones = RegistroGuiones(s.rutas.guiones)
    s.sint = sintetizador
    s.productor = Productor(s.config, s.rutas, sintetizador, fonemizar, lexico or Lexico(), s.guiones,
                            azar=random.Random(1))
    s.cola = cola or Cola(s.productor, trabajadores=1)
    s.srv = crear_servidor(s.cola, sintetizador, "127.0.0.1", 0, s.config.modelos_dir)
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
