import socket
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from cassette_fm.api import crear_servidor
from cassette_fm.cli import main
from cassette_fm.mpv import ErrorMpv
from cassette_fm.radio import EstacionInexistente


class RadioFalsa:
    def __init__(self):
        self.llamadas = []
        self.encendida = True
        self.error = None
        self.llm, self.modo_actual = "ok", "plantillas"
        self.dj = {"activo": False, "hablando": False, "desfase_segundos": None, "intervenciones": []}

    def _hacer(self, nombre, *args, **kw):
        self.llamadas.append((nombre, args, kw))
        if self.error:
            raise self.error

    def estado(self):
        return {"encendida": self.encendida, "estacion": "Regueton 2000",
                "pista": "Daddy Yankee - Gasolina" if self.encendida else None,
                "volumen": 70, "estaciones": ["Lentos", "Regueton 2000"]}

    def estaciones(self):
        return [SimpleNamespace(nombre="Lentos", pistas=(1,) * 37),
                SimpleNamespace(nombre="Regueton 2000", pistas=(1,) * 91)]

    def dj_estado(self):
        return self.dj

    def dj_probar(self, audio=None, en_segundos=20.0):
        self._hacer("dj_probar", audio=audio, en_segundos=en_segundos)
        return {"estacion": "Regueton 2000", "inicio": 1.0, "duracion": 8.0,
                "pista_destino": "/m/Daddy Yankee - Gasolina.mp3", "en_segundos": 24.6}

    def dj_modo(self, nuevo=None):
        self._hacer("dj_modo", nuevo=nuevo)
        if nuevo == "llm":
            return {"modo": "llm", "llm": self.llm}
        return {"modo": nuevo or self.modo_actual}

    def dj_pedir(self, en_segundos=20.0):
        self._hacer("dj_pedir", en_segundos=en_segundos)
        return {"id": "x", "estacion": "Regueton 2000", "inicio": 1.0, "en_segundos": 31.2,
                "tema": "Daddy Yankee - Gasolina"}

    def sintonizar(self, nombre): self._hacer("sintonizar", nombre)
    def siguiente(self): self._hacer("siguiente")
    def anterior(self): self._hacer("anterior")
    def encender(self): self._hacer("encender")
    def apagar(self): self._hacer("apagar")
    def silenciar(self): self._hacer("silenciar")
    def alternar(self): self._hacer("alternar")
    def rescan(self): self._hacer("rescan")

    def volumen(self, valor=None, delta=None):
        self._hacer("volumen", valor=valor, delta=delta)


@pytest.fixture
def servicio(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    radio = RadioFalsa()
    srv = crear_servidor(radio, "127.0.0.1", 0, emisoras=Path("/m/estaciones.json"))
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True).start()
    srv.radio = radio
    srv.puerto = str(srv.server_address[1])
    yield srv
    srv.shutdown()
    srv.server_close()


def test_status_encendida(servicio, capsys):
    assert main(["status", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.strip() == "▶ Regueton 2000 — Daddy Yankee - Gasolina (vol 70)"


def test_status_apagada(servicio, capsys):
    servicio.radio.encendida = False
    assert main(["status", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.strip() == "⏹ apagada (vol 70)"


def test_puerto_antes_del_subcomando(servicio, capsys):
    assert main(["--puerto", servicio.puerto, "status"]) == 0


def test_puerto_sale_de_la_config(servicio, tmp_path, capsys):
    d = tmp_path / "cassette-fm"
    d.mkdir()
    (d / "config.toml").write_text(f"puerto = {servicio.puerto}\n")
    assert main(["status"]) == 0


def test_tune_con_espacios_sin_comillas(servicio):
    assert main(["tune", "Regueton", "2000", "--puerto", servicio.puerto]) == 0
    assert servicio.radio.llamadas == [("sintonizar", ("Regueton 2000",), {})]


def test_tune_con_acentos(servicio):
    assert main(["tune", "Música", "Ñandú", "--puerto", servicio.puerto]) == 0
    assert servicio.radio.llamadas == [("sintonizar", ("Música Ñandú",), {})]


@pytest.mark.parametrize("arg,esperado", [
    ("+5", {"valor": None, "delta": 5}),
    ("-5", {"valor": None, "delta": -5}),
    ("70", {"valor": 70, "delta": None}),
])
def test_vol_relativo_y_absoluto(servicio, arg, esperado):
    assert main(["vol", arg, "--puerto", servicio.puerto]) == 0
    assert servicio.radio.llamadas == [("volumen", (), esperado)]


def test_list_marca_la_actual(servicio, capsys):
    assert main(["list", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "  Lentos (37 temas)", "▶ Regueton 2000 (91 temas)"]


@pytest.mark.parametrize("comando,ruta", [
    ("next", "siguiente"), ("prev", "anterior"), ("on", "encender"),
    ("off", "apagar"), ("toggle", "alternar"), ("mute", "silenciar"), ("rescan", "rescan")])
def test_acciones(servicio, capsys, comando, ruta):
    assert main([comando, "--puerto", servicio.puerto]) == 0
    assert servicio.radio.llamadas == [(ruta, (), {})]
    assert "Regueton 2000" in capsys.readouterr().out


def test_servicio_caido(capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        libre = s.getsockname()[1]
    assert main(["status", "--puerto", str(libre)]) == 1
    err = capsys.readouterr().err
    assert "cassette-fm no está corriendo" in err and "systemctl --user start cassette-fm" in err


def test_error_de_api(servicio, capsys):
    servicio.radio.error = EstacionInexistente("la estación 'x' no existe")
    assert main(["tune", "x", "--puerto", servicio.puerto]) == 1
    assert "la estación 'x' no existe" in capsys.readouterr().err


def test_error_de_mpv_no_se_confunde_con_servicio_caido(servicio, capsys):
    servicio.radio.error = ErrorMpv("mpv no respondió a 'loadfile'")
    assert main(["next", "--puerto", servicio.puerto]) == 1
    err = capsys.readouterr().err
    assert "mpv no respondió" in err and "no está corriendo" not in err


def test_servicio_que_corta_sin_responder(capsys):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def aceptar_y_cortar():
        c, _ = srv.accept()
        c.recv(4096)
        c.close()

    threading.Thread(target=aceptar_y_cortar, daemon=True).start()
    assert main(["status", "--puerto", str(srv.getsockname()[1])]) == 1
    err = capsys.readouterr().err
    srv.close()
    assert "no está corriendo" not in err and "cortó" in err


def test_config_invalida_da_mensaje_y_codigo_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "cassette-fm").mkdir()
    (tmp_path / "cassette-fm" / "config.toml").write_text('puerto = "x"\n')
    assert main(["status"]) == 1
    assert "config.toml" in capsys.readouterr().err


def test_dj_estado_apagado(servicio, capsys):
    assert main(["dj", "estado", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.strip() == "DJ apagado"


def test_dj_estado_con_intervenciones(servicio, capsys):
    servicio.radio.dj = {"activo": True, "hablando": True, "desfase_segundos": 0.4, "intervenciones": [
        {"estacion": "Lentos", "inicio": 5.0, "duracion": 9.8, "texto": "(clip de prueba)", "en_segundos": 312.0}]}
    assert main(["dj", "estado", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "DJ activo · habla: sí · desfase: 0.4 s",
        "  Lentos · en 312 s · 9.8 s · (clip de prueba)"]


def test_dj_estado_sin_desfase_medido(servicio, capsys):
    servicio.radio.dj = {"activo": True, "hablando": False, "desfase_segundos": None, "intervenciones": []}
    main(["dj", "estado", "--puerto", servicio.puerto])
    assert capsys.readouterr().out.strip() == "DJ activo · habla: no · desfase: —"


def test_dj_probar_imprime_cuando_hablara(servicio, capsys):
    assert main(["dj", "probar", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.strip() == (
        "El DJ va a hablar en 25 s, justo después de que arranque «Daddy Yankee - Gasolina» en Regueton 2000.")
    assert servicio.radio.llamadas == [("dj_probar", (), {"audio": None, "en_segundos": 20.0})]


def test_dj_probar_con_audio_manda_ruta_absoluta(servicio, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert main(["dj", "probar", "--audio", "clip.wav", "--en", "45", "--puerto", servicio.puerto]) == 0
    (llamada,) = servicio.radio.llamadas
    assert str(llamada[2]["audio"]) == str(tmp_path / "clip.wav") and llamada[2]["en_segundos"] == 45.0


def test_dj_probar_error_de_la_api_da_codigo_1(servicio, capsys):
    from cassette_fm.radio import DJInactivo
    servicio.radio.error = DJInactivo("apagado")
    assert main(["dj", "probar", "--puerto", servicio.puerto]) == 1
    assert "activo = true" in capsys.readouterr().err


def test_dj_pedir_imprime_cuando_hablara(servicio, capsys):
    assert main(["dj", "pedir", "--en", "30", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.strip() == (
        "Se le pidió una intervención al servicio DJ para «Daddy Yankee - Gasolina» en Regueton 2000: "
        "va a hablar en 31 s si está lista a tiempo.")
    assert servicio.radio.llamadas == [("dj_pedir", (), {"en_segundos": 30.0})]


def test_dj_pedir_por_defecto_20_segundos(servicio):
    assert main(["dj", "pedir", "--puerto", servicio.puerto]) == 0
    assert servicio.radio.llamadas[0][2] == {"en_segundos": 20.0}


def test_dj_pedir_error_de_la_api_da_codigo_1(servicio, capsys):
    from cassette_fm.radio import DJInactivo
    servicio.radio.error = DJInactivo("sin planificador")
    assert main(["dj", "pedir", "--puerto", servicio.puerto]) == 1
    assert "url" in capsys.readouterr().err


def test_dj_estado_muestra_el_servicio_y_el_pedido_en_curso(servicio, capsys):
    servicio.radio.dj = {"activo": True, "hablando": False, "desfase_segundos": None, "intervenciones": [],
                         "planificador": {"estacion": "Lentos", "servicio": "no responde",
                                          "error": "el servicio DJ no responde en http://x",
                                          "proximo_intento_en": 12.4,
                                          "en_curso": {"id": "x", "estacion": "Lentos", "estado": "trabajando",
                                                       "en_segundos": 80.0}}}
    main(["dj", "estado", "--puerto", servicio.puerto])
    assert capsys.readouterr().out.splitlines() == [
        "DJ activo · habla: no · desfase: —",
        "servicio DJ: no responde (el servicio DJ no responde en http://x) · reintento en 12 s",
        "pedido en curso: Lentos (trabajando)"]
    servicio.radio.dj["planificador"].update(servicio="ok", error=None, proximo_intento_en=None, en_curso=None)
    main(["dj", "estado", "--puerto", servicio.puerto])
    assert capsys.readouterr().out.splitlines()[1:] == ["servicio DJ: ok"]


def test_dj_estado_sin_planificador_no_agrega_lineas(servicio, capsys):
    servicio.radio.dj = {"activo": True, "hablando": False, "desfase_segundos": None, "intervenciones": [],
                         "planificador": None}
    main(["dj", "estado", "--puerto", servicio.puerto])
    assert capsys.readouterr().out.splitlines() == ["DJ activo · habla: no · desfase: —"]


def test_dj_modo_imprime_el_estado(servicio, capsys):
    assert main(["dj", "modo", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.strip() == "Modo del DJ: plantillas."
    servicio.radio.modo_actual = "llm"
    assert main(["dj", "modo", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.splitlines() == ["Modo del DJ: llm.",
                                                    "(vuelve a plantillas al reiniciar el servicio DJ)"]


def test_dj_modo_llm_avisa_si_el_llm_responde_o_no(servicio, capsys):
    assert main(["dj", "modo", "llm", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.splitlines() == ["Modo del DJ: llm (el LLM responde).",
                                                    "(vuelve a plantillas al reiniciar el servicio DJ)"]
    servicio.radio.llm = "no responde"
    assert main(["dj", "modo", "llm", "--puerto", servicio.puerto]) == 0
    assert "¡el LLM no responde!" in capsys.readouterr().out


def test_dj_modo_plantillas(servicio, capsys):
    assert main(["dj", "modo", "plantillas", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.strip() == "Modo del DJ: plantillas."
    assert servicio.radio.llamadas[-1] == ("dj_modo", (), {"nuevo": "plantillas"})


def test_dj_modo_apagado_explica_como_prenderlo(servicio, capsys):
    assert main(["dj", "modo", "apagado", "--puerto", servicio.puerto]) == 0
    salida = capsys.readouterr().out
    assert salida.startswith("Modo del DJ: apagado.") and "cassette dj modo plantillas" in salida
    assert servicio.radio.llamadas[-1] == ("dj_modo", (), {"nuevo": "apagado"})


def test_dj_estado_con_el_dj_apagado_lo_dice(servicio, capsys):
    servicio.radio.dj = {"activo": True, "hablando": False, "desfase_segundos": None, "intervenciones": [],
                         "planificador": {"estacion": "Lentos", "servicio": "ok", "error": None, "apagado": True,
                                          "proximo_intento_en": None, "en_curso": None}}
    main(["dj", "estado", "--puerto", servicio.puerto])
    assert capsys.readouterr().out.splitlines()[1:] == [
        "locutor apagado (para prenderlo: cassette dj modo plantillas o llm)"]


def test_dj_modo_error_de_la_api_da_codigo_1(servicio, capsys):
    from cassette_fm.radio import DJInactivo
    servicio.radio.error = DJInactivo("sin planificador")
    assert main(["dj", "modo", "llm", "--puerto", servicio.puerto]) == 1
    assert "url" in capsys.readouterr().err


def test_dj_modo_argumento_invalido(servicio):
    with pytest.raises(SystemExit):
        main(["dj", "modo", "otro", "--puerto", servicio.puerto])


def test_dj_modo_llm_avisa_si_falta_el_modelo(servicio, capsys):
    servicio.radio.llm = "falta el modelo"
    assert main(["dj", "modo", "llm", "--puerto", servicio.puerto]) == 0
    salida = capsys.readouterr().out
    assert "no está descargado" in salida and "instalar-llm.sh" in salida


def test_serve_con_estaciones_json_roto_sale_con_1(tmp_path, monkeypatch, capsys):
    from cassette_fm import config, servicio
    from cassette_fm.config import ErrorConfig, Rutas
    monkeypatch.setattr(config, "rutas", lambda: Rutas(tmp_path / "c.toml", tmp_path / "e.json",
                                                         tmp_path / "d.json", tmp_path))

    def roto(*a, **k):
        raise ErrorConfig("/x/estaciones.json: línea 3, columna 1: Expecting value")
    monkeypatch.setattr(servicio, "servir", roto)
    assert main(["serve"]) == 1
    assert "estaciones.json: línea 3" in capsys.readouterr().err


def _rutas_tmp(monkeypatch, tmp_path):
    from cassette_fm import config
    from cassette_fm.config import Rutas
    r = Rutas(tmp_path / "c.toml", tmp_path / "s" / "e.json", tmp_path / "ca" / "d.json", tmp_path)
    monkeypatch.setattr(config, "rutas", lambda: r)
    return r


def test_spotify_login_ok(tmp_path, monkeypatch, capsys):
    from cassette_fm.spotify import sesion
    r = _rutas_tmp(monkeypatch, tmp_path)
    llamado = {}
    monkeypatch.setattr(sesion, "login", lambda s, cfg, **kw: llamado.update(archivo=s._archivo, cfg=cfg))
    assert main(["spotify", "login"]) == 0
    assert llamado["archivo"] == r.spotify_token and "Listo" in capsys.readouterr().out


def test_spotify_login_con_error_sale_con_1(tmp_path, monkeypatch, capsys):
    from cassette_fm.spotify import sesion
    _rutas_tmp(monkeypatch, tmp_path)

    def falla(*a, **kw):
        raise sesion.ErrorSesion("cancelaste el permiso en Spotify (access_denied)")
    monkeypatch.setattr(sesion, "login", falla)
    assert main(["spotify", "login"]) == 1
    assert "cancelaste" in capsys.readouterr().err


def test_spotify_estado_muestra_sesion_y_emisoras(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r = _rutas_tmp(monkeypatch, tmp_path)
    r.config.write_text(f'[spotify]\napi_url = "{servidor_http.url}/v1"\n')
    r.spotify_token.parent.mkdir(parents=True, exist_ok=True)
    r.spotify_token.write_text(_json.dumps({"access_token": "A", "refresh_token": "R", "expira": 9e18}))
    r.emisoras.write_text(_json.dumps([{"nombre": "Sing", "fuente": {"spotify": "spotify:playlist:4iHcTVQbU4QvIJV5Xao0fs"}},
                                       {"nombre": "Local", "fuente": {"carpeta": "/m"}}]))
    servidor_http.responder("/v1/me", {"display_name": "Matimed", "product": "premium"})
    servidor_http.responder("/v1/playlists/4iHcTVQbU4QvIJV5Xao0fs/items", {"items": [
        {"is_local": False, "item": {"type": "track", "uri": "spotify:track:44AyOl4qVkzS48vBsbNXaC", "name": "T",
                                     "duration_ms": 1000, "artists": [{"name": "A"}]}}], "next": None})
    servidor_http.responder("/v1/playlists/4iHcTVQbU4QvIJV5Xao0fs", {"snapshot_id": "S", "name": "Sing"})
    assert main(["spotify", "estado"]) == 0
    salida = capsys.readouterr().out
    assert "Matimed (premium)" in salida and "«Sing»: 1 temas (playlist «Sing»)" in salida and "Local" not in salida


def test_spotify_estado_sin_sesion_sale_con_1(tmp_path, monkeypatch, capsys):
    _rutas_tmp(monkeypatch, tmp_path)
    assert main(["spotify", "estado"]) == 1
    assert "cassette spotify login" in capsys.readouterr().err


def test_rescan_espera_mas_que_los_demas_comandos(monkeypatch):
    from cassette_fm import cli
    vistos = []
    monkeypatch.setattr(cli, "_llamar", lambda puerto, metodo, ruta, cuerpo=None, timeout=10: vistos.append(
        (ruta, timeout)) or {"encendida": False, "estacion": None, "volumen": 0, "estaciones": []})
    main(["rescan"])
    main(["next"])
    assert vistos[0] == ("/rescan", 120) and vistos[1][1] == 10


def test_status_muestra_spotify():
    from cassette_fm.cli import _linea_estado
    base = {"encendida": True, "estacion": "Sing", "pista": "A - T", "volumen": 70}
    assert "Spotify" in _linea_estado({**base, "fuente": "spotify"})
    assert "Spotify" not in _linea_estado({**base, "fuente": "carpeta"})


def _soloist_falso_ws(eventos):
    import json as _json
    import socket
    import threading
    from websockets.sync.server import serve

    def atender(ws):
        for crudo in ws:
            if _json.loads(crudo).get("command") == "get_auth_state":
                ws.send(_json.dumps(eventos))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    srv = serve(atender, "127.0.0.1", puerto)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"ws://127.0.0.1:{puerto}"


def _bin_falso(tmp_path, fecha="20261113"):
    b = tmp_path / "soloist"
    b.write_text(f"#!/bin/sh\necho 'soloist 1.3.10.71 build 1794592912 ({fecha}) (g19412df6ea) (linux/x86_64)'\n")
    b.chmod(0o755)
    return b


def test_spotify_estado_muestra_soloist_y_los_dias_que_le_quedan(tmp_path, monkeypatch, capsys):
    import datetime
    from cassette_fm import cli
    r = _rutas_tmp(monkeypatch, tmp_path)
    srv, url = _soloist_falso_ws({"type": "auth_state", "logged_in": True, "is_active": False,
                                  "device_name": "cassette-fm"})
    r.config.write_text(f'[spotify]\nsoloist_ws = "{url}"\nsoloist_bin = "{_bin_falso(tmp_path)}"\n')
    monkeypatch.setattr(cli, "_hoy", lambda: datetime.date(2026, 11, 14))
    try:
        main(["spotify", "estado"])
    finally:
        srv.shutdown()
    salida = capsys.readouterr().out
    assert "Soloist: corriendo · sesión: sí · activo: no" in salida
    assert "build 20261113: vence en 89 días" in salida and "⚠" not in salida


def test_spotify_estado_avisa_si_soloist_esta_por_vencer_o_no_responde(tmp_path, monkeypatch, capsys):
    import datetime
    from cassette_fm import cli
    r = _rutas_tmp(monkeypatch, tmp_path)
    r.config.write_text(f'[spotify]\nsoloist_ws = "ws://127.0.0.1:9"\nsoloist_bin = "{_bin_falso(tmp_path)}"\n')
    monkeypatch.setattr(cli, "_hoy", lambda: datetime.date(2027, 2, 1))
    main(["spotify", "estado"])
    salida = capsys.readouterr().out
    assert "Soloist: no responde" in salida
    assert "⚠ Soloist vence en 10 días" in salida and "actualizar-soloist.sh" in salida


def test_spotify_estado_sin_soloist_instalado(tmp_path, monkeypatch, capsys):
    r = _rutas_tmp(monkeypatch, tmp_path)
    r.config.write_text(f'[spotify]\nsoloist_ws = "ws://127.0.0.1:9"\nsoloist_bin = "{tmp_path / "no-esta"}"\n')
    main(["spotify", "estado"])
    assert "no está instalado" in capsys.readouterr().out


# --- cassette nueva ---

PLAYLIST_NUEVA = "https://open.spotify.com/playlist/4iHcTVQbU4QvIJV5Xao0fs?si=abc"
TEMA = {"is_local": False, "item": {"type": "track", "uri": "spotify:track:44AyOl4qVkzS48vBsbNXaC", "name": "T",
                                    "duration_ms": 200000, "artists": [{"name": "A"}]}}
HAPPY = [{"nombre": "Happy Eighties", "fuente": {"spotify": "spotify:playlist:63xdHPD31lRpaR31ZzRcgc"},
          "dj": {"idioma": "en", "voz": "puck"}}]


def _nueva(monkeypatch, tmp_path, servidor_http, items=(TEMA,), codigo=200, llamar=None):
    """Entorno de `cassette nueva`: config con la API falsa, sesión, una emisora (voz puck), alias puck y sarah, y
    el servicio reemplazado por `llamar` (por defecto anota las rutas)."""
    import json as _json
    from cassette_fm import cli
    r = _rutas_tmp(monkeypatch, tmp_path)
    r.config.write_text(f'[spotify]\napi_url = "{servidor_http.url}/v1"\n')
    r.spotify_token.parent.mkdir(parents=True, exist_ok=True)
    r.spotify_token.write_text(_json.dumps({"access_token": "A", "refresh_token": "R", "expira": 9e18}))
    r.emisoras.write_text(_json.dumps(HAPPY))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / "xdg" / "cassette-dj").mkdir(parents=True)
    (tmp_path / "xdg" / "cassette-dj" / "config.toml").write_text('[voces]\npuck = "am_puck"\nsarah = "af_sarah"\n')
    servidor_http.responder("/v1/playlists/4iHcTVQbU4QvIJV5Xao0fs/items",
                            {"items": list(items), "next": None} if codigo == 200
                            else {"error": {"status": codigo, "message": "Forbidden"}}, codigo)
    servidor_http.responder("/v1/playlists/4iHcTVQbU4QvIJV5Xao0fs", {"snapshot_id": "S", "name": "Synth"})
    rutas = []

    def anotar(puerto, metodo, ruta, cuerpo=None, timeout=10):
        rutas.append((ruta, cuerpo))
        return {"encendida": True, "estacion": "Synthwave F.M.", "pista": None, "volumen": 60, "fuente": "spotify"}
    monkeypatch.setattr(cli, "_llamar", llamar or anotar)
    return r, rutas


def test_nueva_guarda_rescanea_y_sintoniza(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, rutas = _nueva(monkeypatch, tmp_path, servidor_http)
    assert main(["nueva", "Synthwave F.M.", PLAYLIST_NUEVA]) == 0
    assert _json.loads(r.emisoras.read_text())[-1] == {
        "nombre": "Synthwave F.M.", "fuente": {"spotify": PLAYLIST_NUEVA}, "dj": {"idioma": "en", "voz": "sarah"}}
    assert rutas == [("/rescan", None), ("/sintonizar", {"estacion": "Synthwave F.M."})]
    salida = capsys.readouterr().out
    assert "✓ Synthwave F.M. (1 temas) · DJ: sarah (en)" in salida and "▶ Synthwave F.M. · Spotify" in salida


def test_nueva_con_nombre_repetido_no_baja_nada(tmp_path, monkeypatch, capsys, servidor_http):
    r, rutas = _nueva(monkeypatch, tmp_path, servidor_http)
    antes = r.emisoras.read_text()
    assert main(["nueva", "happy eighties", PLAYLIST_NUEVA]) == 1
    assert "Happy Eighties" in capsys.readouterr().err
    assert servidor_http.pedidos == [] and rutas == [] and r.emisoras.read_text() == antes


def test_nueva_con_link_que_no_es_playlist(tmp_path, monkeypatch, capsys, servidor_http):
    _nueva(monkeypatch, tmp_path, servidor_http)
    assert main(["nueva", "X", "https://open.spotify.com/album/4iHcTVQbU4QvIJV5Xao0fs"]) == 1
    assert "playlist" in capsys.readouterr().err and servidor_http.pedidos == []


def test_nueva_con_playlist_ajena_no_guarda(tmp_path, monkeypatch, capsys, servidor_http):
    r, rutas = _nueva(monkeypatch, tmp_path, servidor_http, codigo=403)
    antes = r.emisoras.read_text()
    assert main(["nueva", "X", PLAYLIST_NUEVA]) == 1
    assert "no es tuya" in capsys.readouterr().err and r.emisoras.read_text() == antes and rutas == []


def test_nueva_con_playlist_vacia_no_guarda(tmp_path, monkeypatch, capsys, servidor_http):
    r, rutas = _nueva(monkeypatch, tmp_path, servidor_http, items=())
    antes = r.emisoras.read_text()
    assert main(["nueva", "X", PLAYLIST_NUEVA]) == 1
    assert "vacía" in capsys.readouterr().err and r.emisoras.read_text() == antes and rutas == []


def test_nueva_con_voz_e_idioma_que_no_coinciden(tmp_path, monkeypatch, capsys, servidor_http):
    r, _ = _nueva(monkeypatch, tmp_path, servidor_http)
    assert main(["nueva", "X", PLAYLIST_NUEVA, "--voz", "sarah", "--idioma", "es"]) == 1
    assert "sarah" in capsys.readouterr().err and servidor_http.pedidos == []


def test_nueva_con_el_servicio_caido_queda_guardada(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    from cassette_fm import cli

    def caido(*a, **kw):
        raise cli._ServicioCaido("cassette-fm no está corriendo. Arrancalo con: systemctl --user start cassette-fm")
    r, _ = _nueva(monkeypatch, tmp_path, servidor_http, llamar=caido)
    assert main(["nueva", "Synthwave F.M.", PLAYLIST_NUEVA]) == 0
    assert _json.loads(r.emisoras.read_text())[-1]["nombre"] == "Synthwave F.M."
    assert "cuando arranque" in capsys.readouterr().out


def test_nueva_que_la_radio_no_puede_sintonizar_lo_dice(tmp_path, monkeypatch, capsys, servidor_http):
    from cassette_fm import cli

    def sin_emisora(puerto, metodo, ruta, cuerpo=None, timeout=10):
        if ruta == "/sintonizar":
            raise cli._ErrorCli("no existe la estación «Synthwave F.M.»")
        return {}
    _nueva(monkeypatch, tmp_path, servidor_http, llamar=sin_emisora)
    assert main(["nueva", "Synthwave F.M.", PLAYLIST_NUEVA]) == 1
    salida = capsys.readouterr()
    assert "no existe la estación" in salida.err and "cuando arranque" not in salida.out + salida.err


def test_nueva_con_una_voz_cruda_mal_escrita_no_guarda(tmp_path, monkeypatch, capsys, servidor_http):
    r, rutas = _nueva(monkeypatch, tmp_path, servidor_http)
    antes = r.emisoras.read_text()
    assert main(["nueva", "X", PLAYLIST_NUEVA, "--voz", "af_sarah "]) == 1     # la radio no arrancaría con esto
    assert "voz" in capsys.readouterr().err
    assert servidor_http.pedidos == [] and rutas == [] and r.emisoras.read_text() == antes


def test_nueva_con_otra_emisora_invalida_no_baja_ni_guarda(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, rutas = _nueva(monkeypatch, tmp_path, servidor_http)
    r.emisoras.write_text(_json.dumps([{**HAPPY[0], "dj": {"idioma": "fr", "voz": "puck"}}]))
    antes = r.emisoras.read_text()
    assert main(["nueva", "X", PLAYLIST_NUEVA]) == 1
    assert "idioma" in capsys.readouterr().err
    assert servidor_http.pedidos == [] and rutas == [] and r.emisoras.read_text() == antes


def test_nueva_con_un_rescan_que_falla_lo_dice(tmp_path, monkeypatch, capsys, servidor_http):
    from cassette_fm import cli

    def rescan_roto(puerto, metodo, ruta, cuerpo=None, timeout=10):
        raise cli._ErrorCli("estaciones.json: algo anda mal")
    _nueva(monkeypatch, tmp_path, servidor_http, llamar=rescan_roto)
    assert main(["nueva", "Synthwave F.M.", PLAYLIST_NUEVA]) == 1
    salida = capsys.readouterr()
    assert "algo anda mal" in salida.err and "cuando arranque" not in salida.out + salida.err


def test_voces_json_para_el_applet(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    _nueva(monkeypatch, tmp_path, servidor_http)
    assert main(["voces", "--json"]) == 0
    assert _json.loads(capsys.readouterr().out) == [
        {"alias": "puck", "voz": "am_puck", "idioma": "en", "emisoras": ["Happy Eighties"]},
        {"alias": "sarah", "voz": "af_sarah", "idioma": "en", "emisoras": []}]


def test_voces_sin_estaciones_json_lista_igual(tmp_path, monkeypatch, capsys, servidor_http):
    r, _ = _nueva(monkeypatch, tmp_path, servidor_http)
    r.emisoras.unlink()
    assert main(["voces"]) == 0
    salida = capsys.readouterr().out
    assert "puck" in salida and "am_puck" in salida and "sarah" in salida


def test_voces_sin_alias_dice_donde_se_definen(tmp_path, monkeypatch, capsys, servidor_http):
    _nueva(monkeypatch, tmp_path, servidor_http)
    (tmp_path / "xdg" / "cassette-dj" / "config.toml").write_text("")
    assert main(["voces"]) == 0
    assert "[voces]" in capsys.readouterr().out


def test_voces_con_la_config_del_dj_rota_da_un_error_legible(tmp_path, monkeypatch, capsys, servidor_http):
    _nueva(monkeypatch, tmp_path, servidor_http)
    (tmp_path / "xdg" / "cassette-dj" / "config.toml").write_text("[voces\n")
    assert main(["voces", "--json"]) == 1
    error = capsys.readouterr().err
    assert "config.toml" in error and "Traceback" not in error


def test_nueva_con_un_nombre_que_empieza_con_guion_despues_de_doble_guion(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, _ = _nueva(monkeypatch, tmp_path, servidor_http)
    assert main(["nueva", "--voz", "sarah", "--", "-80s-", PLAYLIST_NUEVA]) == 0      # como lo llama el applet
    assert _json.loads(r.emisoras.read_text())[-1]["nombre"] == "-80s-"


SING = {"nombre": "Sing", "fuente": {"spotify": "x"}, "dj": {"idioma": "es", "voz": "dora"}}


def _borrar(monkeypatch, tmp_path, servidor_http, respuesta="s", terminal=True):
    import json as _json
    r, rutas = _nueva(monkeypatch, tmp_path, servidor_http)
    r.emisoras.write_text(_json.dumps(HAPPY + [SING], ensure_ascii=False))
    monkeypatch.setattr("sys.stdin.isatty", lambda: terminal)
    monkeypatch.setattr("builtins.input", lambda texto: print(texto, end="") or respuesta)
    return r, rutas


def test_borrar_pregunta_borra_y_rescanea(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, rutas = _borrar(monkeypatch, tmp_path, servidor_http, respuesta="S")
    assert main(["borrar", "  sing "]) == 0
    assert _json.loads(r.emisoras.read_text()) == HAPPY
    salida = capsys.readouterr().out
    assert "¿Borro «Sing» (Spotify)? (s/N)" in salida and "✗ Sing · ya no está en estaciones.json" in salida
    assert [ruta for ruta, _ in rutas] == ["/rescan"]


def test_borrar_con_otra_respuesta_no_borra(tmp_path, monkeypatch, capsys, servidor_http):
    r, rutas = _borrar(monkeypatch, tmp_path, servidor_http, respuesta="n")
    antes = r.emisoras.read_text()
    assert main(["borrar", "Sing"]) == 1
    assert r.emisoras.read_text() == antes and "No se borró nada." in capsys.readouterr().out and rutas == []


def test_borrar_sin_terminal_pide_si(tmp_path, monkeypatch, capsys, servidor_http):
    r, rutas = _borrar(monkeypatch, tmp_path, servidor_http, terminal=False)
    antes = r.emisoras.read_text()
    assert main(["borrar", "Sing"]) == 1
    assert "--si" in capsys.readouterr().err and r.emisoras.read_text() == antes and rutas == []


def test_borrar_con_si_no_pregunta_y_puede_dejar_la_lista_vacia(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, _ = _borrar(monkeypatch, tmp_path, servidor_http)

    def no_preguntes(texto):
        raise AssertionError("no tenía que preguntar")
    monkeypatch.setattr("builtins.input", no_preguntes)
    assert main(["borrar", "--si", "Sing"]) == 0 and main(["borrar", "--si", "happy eighties"]) == 0
    assert _json.loads(r.emisoras.read_text()) == []


def test_borrar_una_que_no_existe_lista_las_que_hay(tmp_path, monkeypatch, capsys, servidor_http):
    _borrar(monkeypatch, tmp_path, servidor_http)
    assert main(["borrar", "Nada"]) == 1
    assert "Happy Eighties" in capsys.readouterr().err


def test_borrar_con_la_radio_apagada_lo_dice(tmp_path, monkeypatch, capsys, servidor_http):
    from cassette_fm import cli
    _borrar(monkeypatch, tmp_path, servidor_http)

    def caido(*a, **k):
        raise cli._ServicioCaido("cassette-fm no está corriendo")
    monkeypatch.setattr(cli, "_llamar", caido)
    assert main(["borrar", "--si", "Sing"]) == 0
    assert "La radio no está corriendo: el cambio se ve al prenderla." in capsys.readouterr().out


def _renombrar(monkeypatch, tmp_path, servidor_http, sonando=None):
    import json as _json
    from cassette_fm import cli
    r, _ = _nueva(monkeypatch, tmp_path, servidor_http)
    r.emisoras.write_text(_json.dumps(HAPPY + [SING], ensure_ascii=False))
    rutas = []

    def llamar(puerto, metodo, ruta, cuerpo=None, timeout=10):
        rutas.append((ruta, cuerpo))
        estacion = cuerpo["estacion"] if ruta == "/sintonizar" else (sonando or "Happy Eighties")
        return {"encendida": True, "estacion": estacion, "pista": None, "volumen": 60, "fuente": "spotify"}
    monkeypatch.setattr(cli, "_llamar", llamar)
    return r, rutas


def test_renombrar_cambia_solo_el_nombre(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, rutas = _renombrar(monkeypatch, tmp_path, servidor_http)
    assert main(["renombrar", " SING ", "Cantemos"]) == 0
    assert _json.loads(r.emisoras.read_text()) == HAPPY + [dict(SING, nombre="Cantemos")]
    assert "✎ Sing → Cantemos" in capsys.readouterr().out
    assert [ruta for ruta, _ in rutas] == ["/estado", "/rescan"]


def test_renombrar_la_que_suena_la_vuelve_a_sintonizar(tmp_path, monkeypatch, capsys, servidor_http):
    _, rutas = _renombrar(monkeypatch, tmp_path, servidor_http, sonando="Sing")
    assert main(["renombrar", "sing", "Cantemos"]) == 0
    assert rutas[-1] == ("/sintonizar", {"estacion": "Cantemos"})
    assert [ruta for ruta, _ in rutas] == ["/estado", "/rescan", "/sintonizar"]
    assert "▶ Cantemos" in capsys.readouterr().out


def test_renombrar_solo_las_mayusculas(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, _ = _renombrar(monkeypatch, tmp_path, servidor_http)
    assert main(["renombrar", "sing", "SING"]) == 0
    assert _json.loads(r.emisoras.read_text())[-1]["nombre"] == "SING"


def test_renombrar_igual_no_toca_nada(tmp_path, monkeypatch, capsys, servidor_http):
    r, rutas = _renombrar(monkeypatch, tmp_path, servidor_http)
    antes = r.emisoras.read_text()
    assert main(["renombrar", "sing", " Sing "]) == 0
    assert "«Sing» ya se llama así." in capsys.readouterr().out and r.emisoras.read_text() == antes and rutas == []


def test_renombrar_a_un_nombre_de_otra_emisora(tmp_path, monkeypatch, capsys, servidor_http):
    r, rutas = _renombrar(monkeypatch, tmp_path, servidor_http)
    antes = r.emisoras.read_text()
    assert main(["renombrar", "Sing", "happy eighties"]) == 1
    assert "Happy Eighties" in capsys.readouterr().err and r.emisoras.read_text() == antes and rutas == []


def test_renombrar_a_un_nombre_vacio(tmp_path, monkeypatch, capsys, servidor_http):
    r, rutas = _renombrar(monkeypatch, tmp_path, servidor_http)
    antes = r.emisoras.read_text()
    assert main(["renombrar", "Sing", "  "]) == 1
    assert r.emisoras.read_text() == antes and rutas == []


def test_renombrar_una_que_no_existe(tmp_path, monkeypatch, capsys, servidor_http):
    _renombrar(monkeypatch, tmp_path, servidor_http)
    assert main(["renombrar", "Nada", "X"]) == 1
    assert "Happy Eighties" in capsys.readouterr().err


def test_renombrar_con_la_radio_apagada(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    from cassette_fm import cli
    r, _ = _renombrar(monkeypatch, tmp_path, servidor_http)

    def caido(*a, **k):
        raise cli._ServicioCaido("cassette-fm no está corriendo")
    monkeypatch.setattr(cli, "_llamar", caido)
    assert main(["renombrar", "Sing", "Cantemos"]) == 0
    assert _json.loads(r.emisoras.read_text())[-1]["nombre"] == "Cantemos"
    assert "La radio no está corriendo: el cambio se ve al prenderla." in capsys.readouterr().out


def test_nueva_con_icono_lo_copia_y_lo_guarda(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, _ = _nueva(monkeypatch, tmp_path, servidor_http)
    logo = tmp_path / "Mis imágenes" / "synth.png"
    logo.parent.mkdir()
    logo.write_bytes(b"png")
    assert main(["nueva", "--icono", str(logo), "Synthwave F.M.", PLAYLIST_NUEVA]) == 0
    assert _json.loads(r.emisoras.read_text())[-1]["icono"] == "iconos/synth.png"
    assert (r.emisoras.parent / "iconos" / "synth.png").read_bytes() == b"png"


def test_nueva_con_un_icono_que_no_existe_no_guarda(tmp_path, monkeypatch, capsys, servidor_http):
    r, _ = _nueva(monkeypatch, tmp_path, servidor_http)
    antes = r.emisoras.read_text()
    assert main(["nueva", "--icono", str(tmp_path / "no.png"), "Synthwave F.M.", PLAYLIST_NUEVA]) == 1
    assert r.emisoras.read_text() == antes


def test_icono_pone_y_quitar_saca_sin_borrar_el_archivo(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, rutas = _borrar(monkeypatch, tmp_path, servidor_http)
    logo = tmp_path / "power.png"
    logo.write_bytes(b"png")
    assert main(["icono", "sing", str(logo)]) == 0
    assert _json.loads(r.emisoras.read_text())[-1]["icono"] == "iconos/power.png"
    assert "🖼 Sing · iconos/power.png" in capsys.readouterr().out
    assert main(["icono", "SING", "--quitar"]) == 0
    assert "icono" not in _json.loads(r.emisoras.read_text())[-1]
    assert "🖼 Sing · sin logo" in capsys.readouterr().out
    assert (r.emisoras.parent / "iconos" / "power.png").exists()
    assert [ruta for ruta, _ in rutas] == ["/rescan", "/rescan"]


def test_icono_sin_ruta_ni_quitar_es_error(tmp_path, monkeypatch, capsys, servidor_http):
    _borrar(monkeypatch, tmp_path, servidor_http)
    assert main(["icono", "Sing"]) == 1
    assert "--quitar" in capsys.readouterr().err


def test_icono_de_una_emisora_que_no_existe(tmp_path, monkeypatch, capsys, servidor_http):
    _borrar(monkeypatch, tmp_path, servidor_http)
    assert main(["icono", "Nada", "--quitar"]) == 1
    assert "Happy Eighties" in capsys.readouterr().err


def test_icono_con_la_radio_apagada(tmp_path, monkeypatch, capsys, servidor_http):
    from cassette_fm import cli
    _borrar(monkeypatch, tmp_path, servidor_http)

    def caido(*a, **k):
        raise cli._ServicioCaido("cassette-fm no está corriendo")
    monkeypatch.setattr(cli, "_llamar", caido)
    assert main(["icono", "Sing", "--quitar"]) == 0
    assert "La radio no está corriendo: el cambio se ve al prenderla." in capsys.readouterr().out


def _rutas_lan(tmp_path, monkeypatch, toml=""):
    from cassette_fm import config
    from cassette_fm.config import Rutas
    r = Rutas(tmp_path / "c" / "config.toml", tmp_path / "e.json", tmp_path / "d.json", tmp_path)
    r.config.parent.mkdir(parents=True)
    r.config.write_text(toml)
    monkeypatch.setattr(config, "rutas", lambda: r)
    return r


def test_cassette_lan_muestra_la_direccion_y_crea_la_clave(tmp_path, monkeypatch, capsys):
    from cassette_fm import lan_acceso
    r = _rutas_lan(tmp_path, monkeypatch, "[lan]\nactivo = true\n")
    monkeypatch.setattr(lan_acceso, "ip_tailscale", lambda *a, **k: "100.104.222.41")
    assert main(["lan"]) == 0
    salida = capsys.readouterr().out
    token = r.lan_token.read_text().strip()
    assert "http://100.104.222.41:8765" in salida and token in salida


def test_cassette_lan_regenerar_cambia_la_clave(tmp_path, monkeypatch, capsys):
    r = _rutas_lan(tmp_path, monkeypatch, "[lan]\nactivo = true\n")
    main(["lan"])
    viejo = r.lan_token.read_text().strip()
    capsys.readouterr()
    assert main(["lan", "regenerar"]) == 0
    nuevo = r.lan_token.read_text().strip()
    assert nuevo != viejo and nuevo in capsys.readouterr().out


def test_cassette_lan_con_lan_apagado_avisa_como_activarlo_y_igual_muestra_los_datos(tmp_path, monkeypatch, capsys):
    _rutas_lan(tmp_path, monkeypatch)
    assert main(["lan"]) == 0
    salida = capsys.readouterr().out
    assert "[lan]" in salida and "activo = true" in salida and "http://" in salida


from cassette_fm import cli  # noqa: E402


def test_cassette_nube_muestra_url_conexion_y_clave(tmp_path, monkeypatch, capsys):
    r = _rutas_lan(tmp_path, monkeypatch, '[nube]\nactivo = true\nurl = "wss://relay.ejemplo.com"\n')
    monkeypatch.setattr(cli, "_llamar", lambda *a, **k: {"nube": {"conectado": True, "subiendo": [64, 96]}})
    assert main(["nube"]) == 0
    salida = capsys.readouterr().out
    token = r.nube_token.read_text().strip()
    assert "wss://relay.ejemplo.com" in salida and token in salida and "conectado" in salida and "64, 96" in salida


def test_cassette_nube_desconectada_lo_dice(tmp_path, monkeypatch, capsys):
    _rutas_lan(tmp_path, monkeypatch, '[nube]\nactivo = true\nurl = "wss://relay.ejemplo.com"\n')
    monkeypatch.setattr(cli, "_llamar", lambda *a, **k: {"nube": {"conectado": False, "subiendo": []}})
    assert main(["nube"]) == 0
    assert "sin conexión" in capsys.readouterr().out


def test_cassette_nube_regenerar(tmp_path, monkeypatch, capsys):
    r = _rutas_lan(tmp_path, monkeypatch, '[nube]\nactivo = true\nurl = "wss://relay.ejemplo.com"\n')
    monkeypatch.setattr(cli, "_llamar", lambda *a, **k: {})
    main(["nube"])
    viejo = r.nube_token.read_text().strip()
    capsys.readouterr()
    assert main(["nube", "regenerar"]) == 0
    nuevo = r.nube_token.read_text().strip()
    salida = capsys.readouterr().out
    assert nuevo != viejo and nuevo in salida and "relay" in salida


def test_cassette_nube_apagada_explica_como_prenderla(tmp_path, monkeypatch, capsys):
    _rutas_lan(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "_llamar", lambda *a, **k: {})
    assert main(["nube"]) == 0
    salida = capsys.readouterr().out
    assert "[nube]" in salida and "activo = true" in salida and "url" in salida


def test_cassette_nube_con_la_radio_parada(tmp_path, monkeypatch, capsys):
    _rutas_lan(tmp_path, monkeypatch, '[nube]\nactivo = true\nurl = "wss://relay.ejemplo.com"\n')

    def caido(*a, **k):
        raise cli._ServicioCaido("cassette-fm no está corriendo")
    monkeypatch.setattr(cli, "_llamar", caido)
    assert main(["nube"]) == 0
    assert "no está corriendo" in capsys.readouterr().out
