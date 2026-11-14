from pathlib import Path

import pytest

from cassette_fm.config import ErrorConfig
from cassette_fm.dj.cli import main
from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ, cargar_config_dj, rutas_dj


def test_defaults():
    c = ConfigServicioDJ()
    assert (c.host, c.puerto, c.trabajadores) == ("127.0.0.1", 7720, 1)
    assert (c.retencion_minutos, c.descargar_tras_minutos) == (60.0, 5.0)
    assert c.modelos_dir == Path.home() / ".local/share/cassette-dj/modelos"
    assert (c.palabras_maximas, c.velocidad) == (45, 1.05)
    assert (c.pausa_oracion_segundos, c.pausa_coma_segundos, c.continuo) == (0.25, 0.1, False)
    assert c.zona_horaria == "America/Argentina/Buenos_Aires"


def test_archivo_ausente_da_los_defaults(tmp_path):
    assert cargar_config_dj(tmp_path / "no-existe.toml") == ConfigServicioDJ()


def test_lee_el_toml_y_acepta_enteros_como_float(tmp_path):
    archivo = tmp_path / "config.toml"
    archivo.write_text('host = "0.0.0.0"\npuerto = 8000\ntrabajadores = 2\nretencion_minutos = 30\n'
                       'modelos_dir = "~/modelos"\nvelocidad = 1\ncontinuo = true\n')
    c = cargar_config_dj(archivo)
    assert (c.host, c.puerto, c.trabajadores, c.continuo) == ("0.0.0.0", 8000, 2, True)
    assert c.retencion_minutos == 30.0 and isinstance(c.retencion_minutos, float)
    assert c.velocidad == 1.0 and isinstance(c.velocidad, float)
    assert c.modelos_dir == Path.home() / "modelos"


def test_ignora_claves_desconocidas(tmp_path):
    archivo = tmp_path / "config.toml"
    archivo.write_text('puerto = 9000\nquien_sabe = 1\n[tabla_rara]\nx = 2\n')
    assert cargar_config_dj(archivo).puerto == 9000


@pytest.mark.parametrize("contenido", [
    "puerto = 0", 'puerto = "x"', "puerto = true", "puerto = 70000",
    "trabajadores = 0", "palabras_maximas = 2", "velocidad = 3", "velocidad = 0.1",
    "pausa_oracion_segundos = -1", "pausa_coma_segundos = -0.5", "descargar_tras_minutos = -1",
    "retencion_minutos = 0", 'host = ""', 'zona_horaria = "Marte/Olimpo"', 'continuo = "si"',
    "esto no es toml =", 'modelos_dir = ""', 'modelos_dir = "relativo/dir"', 'modelos_dir = "."',
])
def test_invalido_da_error_claro(tmp_path, contenido):
    archivo = tmp_path / "config.toml"
    archivo.write_text(contenido + "\n")
    with pytest.raises(ErrorConfig) as exc:
        cargar_config_dj(archivo)
    assert str(archivo) in str(exc.value)


def test_rutas_respetan_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "k"))
    r = rutas_dj()
    assert r.config == tmp_path / "c" / "cassette-dj" / "config.toml"
    assert r.estado == tmp_path / "s" / "cassette-dj"
    assert r.clips == tmp_path / "k" / "cassette-dj" / "clips"
    assert r.guiones == tmp_path / "s" / "cassette-dj" / "guiones.jsonl"
    assert r.lexico == tmp_path / "c" / "cassette-dj" / "lexico.toml"


def test_rutas_sin_xdg_usan_los_defaults(monkeypatch):
    for v in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(v, raising=False)
    r = rutas_dj()
    home = Path.home()
    assert r.config == home / ".config" / "cassette-dj" / "config.toml"
    assert r.estado == home / ".local" / "state" / "cassette-dj"
    assert r.clips == home / ".cache" / "cassette-dj" / "clips"


def test_cli_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() != ""


def test_modelos_dir_acepta_absoluta_y_tilde(tmp_path):
    archivo = tmp_path / "c.toml"
    archivo.write_text('modelos_dir = "/opt/modelos"\n')
    assert cargar_config_dj(archivo).modelos_dir == Path("/opt/modelos")
    archivo.write_text('modelos_dir = "~/modelos"\n')
    assert cargar_config_dj(archivo).modelos_dir == Path.home() / "modelos"
