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
