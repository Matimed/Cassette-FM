import json
import socket
import threading
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest

from cassette_fm.config import ConfigSpotify
from cassette_fm.spotify.sesion import ESCOPOS, ErrorSesion, Sesion, login


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def configurar(servidor_http, **kw):
    return ConfigSpotify(cuentas_url=servidor_http.url, puerto_login=puerto_libre(), timeout_segundos=2.0, **kw)


def navegador(respuesta=lambda q: f"code=C1&state={q['state'][0]}", validar=None):
    """Hace de navegador: recibe la URL de autorización y llama al callback."""
    def abrir(url):
        q = parse_qs(urlparse(url).query)
        if validar:
            validar(q)
        destino = f"{q['redirect_uri'][0]}?{respuesta(q)}"
        threading.Thread(target=lambda: urllib.request.urlopen(destino, timeout=5).read(), daemon=True).start()
    return abrir


def guardado(archivo):
    return json.loads(archivo.read_text())


def test_login_completo_guarda_el_token(tmp_path, servidor_http):
    servidor_http.responder("/api/token", {"access_token": "A1", "refresh_token": "R1", "expires_in": 3600})
    cfg = configurar(servidor_http)
    s = Sesion(tmp_path / "t.json", cfg, reloj=lambda: 1000.0)

    def validar(q):
        assert q["code_challenge_method"] == ["S256"] and q["client_id"] == [cfg.client_id]
        assert q["redirect_uri"] == [f"http://127.0.0.1:{cfg.puerto_login}/callback"]
        assert q["scope"] == [ESCOPOS] and "playlist-read-private" in ESCOPOS and q["response_type"] == ["code"]

    login(s, cfg, abrir=navegador(validar=validar), timeout=5)
    assert s.token() == "A1"
    assert oct((tmp_path / "t.json").stat().st_mode)[-3:] == "600"
    ((ruta, cuerpo),) = servidor_http.cuerpos
    datos = parse_qs(cuerpo.decode())
    assert ruta == "/api/token" and datos["grant_type"] == ["authorization_code"] and datos["code"] == ["C1"]
    assert datos["client_id"] == [cfg.client_id] and len(datos["code_verifier"][0]) >= 43
    assert datos["redirect_uri"] == [f"http://127.0.0.1:{cfg.puerto_login}/callback"]


def test_login_cancelado_no_guarda(tmp_path, servidor_http):
    cfg = configurar(servidor_http)
    s = Sesion(tmp_path / "t.json", cfg)
    with pytest.raises(ErrorSesion, match="cancelaste"):
        login(s, cfg, abrir=navegador(respuesta=lambda q: f"error=access_denied&state={q['state'][0]}"), timeout=5)
    assert not (tmp_path / "t.json").exists()


def test_login_con_state_ajeno_se_ignora_y_vence(tmp_path, servidor_http):
    cfg = configurar(servidor_http)
    s = Sesion(tmp_path / "t.json", cfg)
    with pytest.raises(ErrorSesion, match="no llegó"):
        login(s, cfg, abrir=navegador(respuesta=lambda q: "code=C1&state=otro"), timeout=1)
    assert not (tmp_path / "t.json").exists() and servidor_http.cuerpos == []


def test_login_con_el_puerto_ocupado(tmp_path, servidor_http):
    cfg = configurar(servidor_http)
    with socket.socket() as ocupado:
        ocupado.bind(("127.0.0.1", cfg.puerto_login))
        ocupado.listen()
        with pytest.raises(ErrorSesion, match="ocupado"):
            login(Sesion(tmp_path / "t.json", cfg), cfg, abrir=lambda url: None, timeout=1)


def test_login_sin_respuesta_vence(tmp_path, servidor_http):
    cfg = configurar(servidor_http)
    with pytest.raises(ErrorSesion, match="no llegó"):
        login(Sesion(tmp_path / "t.json", cfg), cfg, abrir=lambda url: None, timeout=0.5)


def escribir_token(archivo, expira, refresh="R1", acceso="A0"):
    archivo.write_text(json.dumps({"access_token": acceso, "refresh_token": refresh, "expira": expira}))


def test_token_vigente_no_llama_a_spotify(tmp_path, servidor_http):
    archivo = tmp_path / "t.json"
    escribir_token(archivo, expira=5000)
    assert Sesion(archivo, configurar(servidor_http), reloj=lambda: 1000.0).token() == "A0"
    assert servidor_http.pedidos == []


def test_token_se_refresca_y_guarda_el_refresh_nuevo(tmp_path, servidor_http):
    archivo = tmp_path / "t.json"
    escribir_token(archivo, expira=1000)
    servidor_http.responder("/api/token", {"access_token": "A2", "refresh_token": "R2", "expires_in": 3600})
    s = Sesion(archivo, configurar(servidor_http), reloj=lambda: 999.5)
    assert s.token() == "A2"
    datos = parse_qs(servidor_http.cuerpos[0][1].decode())
    assert datos["grant_type"] == ["refresh_token"] and datos["refresh_token"] == ["R1"]
    assert guardado(archivo)["refresh_token"] == "R2" and guardado(archivo)["expira"] == 999.5 + 3600


def test_refresh_sin_refresh_token_nuevo_conserva_el_viejo(tmp_path, servidor_http):
    archivo = tmp_path / "t.json"
    escribir_token(archivo, expira=0)
    servidor_http.responder("/api/token", {"access_token": "A2", "expires_in": 3600})
    assert Sesion(archivo, configurar(servidor_http), reloj=lambda: 10.0).token() == "A2"
    assert guardado(archivo)["refresh_token"] == "R1"


def test_token_forzado_refresca_aunque_este_vigente(tmp_path, servidor_http):
    archivo = tmp_path / "t.json"
    escribir_token(archivo, expira=5000)
    servidor_http.responder("/api/token", {"access_token": "A2", "expires_in": 3600})
    assert Sesion(archivo, configurar(servidor_http), reloj=lambda: 1000.0).token(forzar=True) == "A2"


def test_sin_sesion_dice_que_hacer(tmp_path, servidor_http):
    with pytest.raises(ErrorSesion, match="cassette spotify login"):
        Sesion(tmp_path / "no.json", configurar(servidor_http)).token()


def test_refresh_revocado_dice_que_hacer(tmp_path, servidor_http):
    archivo = tmp_path / "t.json"
    escribir_token(archivo, expira=0)
    servidor_http.responder("/api/token", {"error": "invalid_grant", "error_description": "Refresh token revoked"}, 400)
    with pytest.raises(ErrorSesion, match="cassette spotify login") as e:
        Sesion(archivo, configurar(servidor_http), reloj=lambda: 10.0).token()
    assert "R1" not in str(e.value) and "A0" not in str(e.value)


def test_spotify_caido_es_error_de_sesion_sin_tokens(tmp_path):
    archivo = tmp_path / "t.json"
    escribir_token(archivo, expira=0)
    cfg = ConfigSpotify(cuentas_url=f"http://127.0.0.1:{puerto_libre()}", timeout_segundos=1.0)
    with pytest.raises(ErrorSesion, match="no responde") as e:
        Sesion(archivo, cfg, reloj=lambda: 10.0).token()
    assert "R1" not in str(e.value)
