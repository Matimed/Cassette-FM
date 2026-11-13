import os
from pathlib import Path

from cassette_fm.config import (Config, Estado, cargar_config, cargar_estado,
                                guardar_estado, rutas)


def test_config_sin_archivo_usa_defaults(tmp_path):
    assert cargar_config(tmp_path / "no-existe.toml") == Config()


def test_config_lee_toml_y_expande_home(tmp_path):
    archivo = tmp_path / "config.toml"
    archivo.write_text('raiz_musica = "~/X"\npuerto = 8000\navisos = false\n')
    c = cargar_config(archivo)
    assert c == Config(raiz_musica=Path.home() / "X", puerto=8000, avisos=False)


def test_config_ignora_claves_desconocidas(tmp_path):
    archivo = tmp_path / "config.toml"
    archivo.write_text('puerto = 9000\nquien_sabe = 1\n')
    assert cargar_config(archivo).puerto == 9000


def test_estado_ida_y_vuelta(tmp_path):
    archivo = tmp_path / "sub" / "dir" / "estado.json"
    guardar_estado(archivo, Estado("Regueton 2000", 55))
    assert cargar_estado(archivo) == Estado("Regueton 2000", 55)


def test_estado_corrupto_o_ausente_devuelve_default(tmp_path):
    assert cargar_estado(tmp_path / "no-existe.json") == Estado()
    roto = tmp_path / "roto.json"
    roto.write_text("{no es json")
    assert cargar_estado(roto) == Estado()


def test_rutas_respeta_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "k"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "r"))
    r = rutas()
    assert r.config == tmp_path / "c" / "cassette-fm" / "config.toml"
    assert r.estado == tmp_path / "s" / "cassette-fm" / "estado.json"
    assert r.cache == tmp_path / "k" / "cassette-fm" / "duraciones.json"
    assert r.runtime == tmp_path / "r" / "cassette-fm"


def test_rutas_sin_xdg_usa_defaults(monkeypatch):
    for v in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(v, raising=False)
    r = rutas()
    home = Path.home()
    assert r.config == home / ".config" / "cassette-fm" / "config.toml"
    assert r.estado == home / ".local" / "state" / "cassette-fm" / "estado.json"
    assert r.cache == home / ".cache" / "cassette-fm" / "duraciones.json"
    assert r.runtime == Path(f"/tmp/cassette-fm-{os.getuid()}")


def test_normalizar_por_defecto_y_configurable(tmp_path):
    assert Config().normalizar is True
    archivo = tmp_path / "config.toml"
    archivo.write_text("normalizar = false\n")
    assert cargar_config(archivo).normalizar is False
