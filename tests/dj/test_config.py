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


def test_voces_con_nombre(tmp_path):
    assert ConfigServicioDJ().voces == {}
    archivo = tmp_path / "config.toml"
    archivo.write_text('[voces]\nalex_santa = "em_alex+em_santa"\ndaniela = "piper:es_AR-daniela-high"\n')
    assert cargar_config_dj(archivo).voces == {"alex_santa": "em_alex+em_santa",
                                               "daniela": "piper:es_AR-daniela-high"}


@pytest.mark.parametrize("contenido", ['voces = 3', '[voces]\na = 3', '[voces]\n"a b" = "x"', '[voces]\na = "../x"',
                                       '[voces]\n"a+b" = "x"', '[voces]\na = "b"\nb = "em_alex"'])
def test_voces_con_nombre_invalidas(tmp_path, contenido):
    archivo = tmp_path / "config.toml"
    archivo.write_text(contenido + "\n")
    with pytest.raises(ErrorConfig) as e:
        cargar_config_dj(archivo)
    assert str(archivo) in str(e.value)


def test_pausas_de_piper(tmp_path):
    c = ConfigServicioDJ()
    assert (c.piper_pausa_coma_segundos, c.piper_pausa_oracion_segundos) == (0.15, 0.4)
    archivo = tmp_path / "config.toml"
    archivo.write_text("piper_pausa_coma_segundos = 0.2\npiper_pausa_oracion_segundos = 0.6\n")
    c = cargar_config_dj(archivo)
    assert (c.piper_pausa_coma_segundos, c.piper_pausa_oracion_segundos) == (0.2, 0.6)
    archivo.write_text("piper_pausa_coma_segundos = -1\n")
    with pytest.raises(ErrorConfig):
        cargar_config_dj(archivo)


# --- hechos reales (parte 3) ---

def test_defaults_de_los_hechos():
    c = ConfigServicioDJ()
    assert (c.contacto, c.musicbrainz_url, c.open_meteo_url) == ("", "https://musicbrainz.org/ws/2",
                                                                   "https://api.open-meteo.com/v1/forecast")
    assert (c.latitud, c.longitud, c.timeout_hechos_segundos) == (-34.6037, -58.3816, 5.0)
    assert (c.cache_clima_minutos, c.cache_datos_dias, c.cache_sin_dato_dias, c.cache_error_minutos) == (
        15.0, 90.0, 14.0, 10.0)
    assert (c.ingredientes_max, c.penalizacion_reciente) == (3, 0.3)
    assert c.pesos_ingredientes == {"estacion": 0.5, "hora": 0.35, "momento": 0.3, "album": 0.3, "anterior": 0.3,
                                    "clima": 0.12, "dato": 0.25}


def test_contacto_y_urls_se_leen(tmp_path):
    archivo = tmp_path / "config.toml"
    archivo.write_text('contacto = "yo@example.com"\nmusicbrainz_url = "http://127.0.0.1:9/ws/2"\n'
                       'open_meteo_url = "http://127.0.0.1:9/f"\nlatitud = -31.4\nlongitud = -64.2\n'
                       'ingredientes_max = 2\n')
    c = cargar_config_dj(archivo)
    assert (c.contacto, c.musicbrainz_url, c.open_meteo_url) == ("yo@example.com", "http://127.0.0.1:9/ws/2",
                                                                  "http://127.0.0.1:9/f")
    assert (c.latitud, c.longitud, c.ingredientes_max) == (-31.4, -64.2, 2)


def test_ingredientes_se_leen_y_se_funden_con_los_de_fabrica(tmp_path):
    archivo = tmp_path / "config.toml"
    archivo.write_text("[ingredientes]\nclima = 0.5\nhora = 0\n")
    c = cargar_config_dj(archivo)
    assert c.pesos_ingredientes["clima"] == 0.5 and c.pesos_ingredientes["hora"] == 0.0
    assert c.pesos_ingredientes["dato"] == 0.25


@pytest.mark.parametrize("contenido", ["[ingredientes]\ncancion = 1", "[ingredientes]\nclima = 2",
                                       '[ingredientes]\nclima = "x"', "[ingredientes]\ninventado = 0.1",
                                       "ingredientes = 3", "[ingredientes]\nclima = true",
                                       "timeout_hechos_segundos = 0", "ingredientes_max = 0",
                                       "penalizacion_reciente = 1.5", "latitud = 200", "longitud = -181",
                                       'musicbrainz_url = "ftp://x"', 'open_meteo_url = "x"',
                                       "cache_datos_dias = -1", "contacto = 5"])
def test_valores_invalidos_de_los_hechos(tmp_path, contenido):
    archivo = tmp_path / "config.toml"
    archivo.write_text(contenido + "\n")
    with pytest.raises(ErrorConfig) as e:
        cargar_config_dj(archivo)
    assert str(archivo) in str(e.value)


def test_rutas_hechos(tmp_path):
    r = RutasDJ(config=tmp_path / "c.toml", estado=tmp_path / "estado", clips=tmp_path / "clips")
    assert r.hechos == tmp_path / "estado" / "hechos.sqlite"
