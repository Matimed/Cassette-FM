import os

import pytest
from pathlib import Path

from cassette_fm.config import (Config, ErrorConfig, Estado, cargar_config, cargar_estado,
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


@pytest.mark.parametrize("contenido", [
    "esto no es toml =",
    'puerto = "7710"',
    "puerto = 70000",
    'avisos = "si"',
    "normalizar = 1",
    "raiz_musica = 5",
])
def test_config_invalida_da_error_claro(tmp_path, contenido):
    archivo = tmp_path / "config.toml"
    archivo.write_text(contenido + "\n")
    with pytest.raises(ErrorConfig) as exc:
        cargar_config(archivo)
    assert str(archivo) in str(exc.value)


# --- DJ ---

from cassette_fm.config import ConfigDJ, configuracion_dj  # noqa: E402


def test_dj_por_defecto():
    assert Config().dj == ConfigDJ()
    d = ConfigDJ()
    assert d.activo is False
    assert (d.duracion_maxima_segundos, d.retraso_voz_segundos, d.nivel_musica_con_voz,
            d.rampa_bajada_segundos, d.rampa_subida_segundos, d.minimo_restante_segundos,
            d.tolerancia_desfase_segundos, d.desfase_aviso_segundos,
            d.margen_seguridad_voz_segundos) == (15.0, 1.0, 0.35, 0.4, 1.0, 1.5, 60.0, 5.0, 2.0)


def test_dj_lee_la_tabla_y_acepta_enteros(tmp_path):
    archivo = tmp_path / "config.toml"
    archivo.write_text("[dj]\nactivo = true\nduracion_maxima_segundos = 20\nnivel_musica_con_voz = 0.5\n")
    dj = cargar_config(archivo).dj
    assert dj.activo is True and dj.nivel_musica_con_voz == 0.5
    assert dj.duracion_maxima_segundos == 20.0 and isinstance(dj.duracion_maxima_segundos, float)


def test_dj_por_estacion_pisa_a_la_general(tmp_path):
    archivo = tmp_path / "config.toml"
    archivo.write_text('[dj]\nduracion_maxima_segundos = 15\nretraso_voz_segundos = 2\n'
                       '[dj.estaciones."Lentos"]\nduracion_maxima_segundos = 25\n')
    cfg = cargar_config(archivo)
    lentos = configuracion_dj(cfg, "Lentos")
    assert lentos.duracion_maxima_segundos == 25.0
    assert lentos.retraso_voz_segundos == 2.0          # lo demás es el valor general
    assert configuracion_dj(cfg, "Otra").duracion_maxima_segundos == 15.0


def test_dj_ignora_claves_de_otras_partes(tmp_path):
    archivo = tmp_path / "config.toml"
    archivo.write_text('[dj]\nurl = "http://x"\nmargen_minutos = 6\npalabras_maximas = 45\n'
                       'frecuencia = {modo = "temas", min = 2, max = 3}\n'
                       '[dj.estaciones."X"]\nvoz = "em_santa"\nidioma = "es"\npersonalidad = "hola"\n')
    assert cargar_config(archivo).dj == ConfigDJ()


@pytest.mark.parametrize("contenido", [
    "[dj]\nnivel_musica_con_voz = 0",
    "[dj]\nnivel_musica_con_voz = 1.5",
    "[dj]\nduracion_maxima_segundos = 0",
    "[dj]\nduracion_maxima_segundos = -3",
    "[dj]\nrampa_bajada_segundos = -1",
    '[dj]\nretraso_voz_segundos = "uno"',
    '[dj]\nactivo = "si"',
    "[dj]\nestaciones = 5",
    "[dj.estaciones]\nLentos = 3",
    "[dj]\nretraso_voz_segundos = true",
])
def test_dj_invalido_da_error_claro(tmp_path, contenido):
    archivo = tmp_path / "config.toml"
    archivo.write_text(contenido + "\n")
    with pytest.raises(ErrorConfig) as exc:
        cargar_config(archivo)
    assert str(archivo) in str(exc.value)


def test_rutas_del_dj(tmp_path):
    from cassette_fm.config import Rutas
    r = Rutas(config=tmp_path / "c.toml", estado=tmp_path / "s" / "estado.json",
              cache=tmp_path / "k" / "duraciones.json", runtime=tmp_path / "r")
    assert r.intervenciones == tmp_path / "s" / "intervenciones.json"
    assert r.clips == tmp_path / "k" / "dj"
