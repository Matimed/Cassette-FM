import mutagen

from cassette_fm.cli import main


def test_crear_mp3_tiene_duracion_y_tags(tmp_path, crear_mp3):
    p = crear_mp3(tmp_path / "a" / "t.mp3", segundos=3, titulo="Tema", artista="Artista")
    f = mutagen.File(p, easy=True)
    assert abs(f.info.length - 3) < 0.05
    assert f["title"] == ["Tema"] and f["artist"] == ["Artista"]


def test_cli_version(capsys):
    assert main(["--version"]) == 0
    assert "0.1.0" in capsys.readouterr().out


def test_servidor_http_acepta_post_y_encabezados(servidor_http):
    import json
    import urllib.request
    servidor_http.responder("/api/token", {"ok": True}, encabezados={"Retry-After": "2"})
    req = urllib.request.Request(servidor_http.url + "/api/token", data=b"a=1", method="POST")
    with urllib.request.urlopen(req) as r:
        assert json.loads(r.read()) == {"ok": True} and r.headers["Retry-After"] == "2"
    assert servidor_http.cuerpos == [("/api/token", b"a=1")]
