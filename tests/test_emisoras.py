import json

import pytest

from cassette_fm.config import ConfigDJ, ErrorConfig
import logging

from cassette_fm.emisoras import Fuente, leer_emisoras, migrar_emisoras, playlist_de

PLAYLIST = "4iHcTVQbU4QvIJV5Xao0fs"


def escribir(tmp_path, datos):
    archivo = tmp_path / "estaciones.json"
    archivo.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return archivo


# --- lectura y validación ---

def test_lee_carpeta_y_dj_fusionado_con_el_general(tmp_path):
    a = escribir(tmp_path, [{"nombre": "Lentos", "fuente": {"carpeta": str(tmp_path / "m")},
                             "dj": {"voz": "af_nicole", "frecuencia": {"min": 1, "max": 1}}}])
    (e,) = leer_emisoras(a, ConfigDJ(idioma="en", duracion_maxima_segundos=25))
    assert e.nombre == "Lentos" and e.fuente == Fuente("carpeta", str(tmp_path / "m"))
    assert e.dj.voz == "af_nicole" and e.dj.idioma == "en" and e.dj.duracion_maxima_segundos == 25.0
    assert e.dj.frecuencia.min == 1 and e.dj_crudo == {"voz": "af_nicole", "frecuencia": {"min": 1, "max": 1}}


def test_sin_dj_usa_el_general(tmp_path):
    general = ConfigDJ(voz="am_puck")
    (e,) = leer_emisoras(escribir(tmp_path, [{"nombre": "A", "fuente": {"carpeta": "/m"}}]), general)
    assert e.dj == general and e.dj_crudo == {}


def test_respeta_el_orden_del_archivo(tmp_path):
    a = escribir(tmp_path, [{"nombre": "Zeta", "fuente": {"carpeta": "/z"}},
                            {"nombre": "Alfa", "fuente": {"carpeta": "/a"}}])
    assert [e.nombre for e in leer_emisoras(a, ConfigDJ())] == ["Zeta", "Alfa"]


def test_carpeta_con_tilde_se_expande_y_relativa_es_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (e,) = leer_emisoras(escribir(tmp_path, [{"nombre": "A", "fuente": {"carpeta": "~/m"}}]), ConfigDJ())
    assert e.fuente.valor == str(tmp_path / "m")
    with pytest.raises(ErrorConfig, match="absoluta"):
        leer_emisoras(escribir(tmp_path, [{"nombre": "A", "fuente": {"carpeta": "m"}}]), ConfigDJ())


@pytest.mark.parametrize("link", [f"https://open.spotify.com/playlist/{PLAYLIST}?si=3572b2afcfa0465a",
                                  f"https://open.spotify.com/playlist/{PLAYLIST}",
                                  f"https://open.spotify.com/intl-es/playlist/{PLAYLIST}",
                                  f"spotify:playlist:{PLAYLIST}"])
def test_links_de_playlist(link):
    assert playlist_de(link) == PLAYLIST


@pytest.mark.parametrize("link", [f"https://open.spotify.com/album/{PLAYLIST}", f"spotify:track:{PLAYLIST}",
                                  "https://open.spotify.com/playlist/corto", "hola", ""])
def test_lo_que_no_es_una_playlist(link):
    assert playlist_de(link) is None


def test_fuente_spotify_se_guarda_como_id(tmp_path):
    a = escribir(tmp_path, [{"nombre": "Sing", "fuente": {"spotify": f"https://open.spotify.com/playlist/{PLAYLIST}?si=x"}}])
    assert leer_emisoras(a, ConfigDJ())[0].fuente == Fuente("spotify", PLAYLIST)


@pytest.mark.parametrize("datos, mensaje", [
    ({"nombre": "A", "fuente": {"spotify": "spotify:album:x"}}, "playlist"),
    ({"nombre": "A", "fuente": {"carpeta": "/m", "spotify": f"spotify:playlist:{PLAYLIST}"}}, "una sola"),
    ({"nombre": "A", "fuente": {}}, "una sola"),
    ({"nombre": "A", "fuente": {"cassette": "/m"}}, "carpeta"),
    ({"nombre": "A", "fuente": {"carpeta": 3}}, "carpeta"),
    ({"nombre": "", "fuente": {"carpeta": "/m"}}, "nombre"),
    ({"nombre": "   ", "fuente": {"carpeta": "/m"}}, "nombre"),
    ({"fuente": {"carpeta": "/m"}}, "nombre"),
    ({"nombre": "A"}, "fuente"),
    ({"nombre": "A", "fuente": "/m"}, "fuente"),
    ({"nombre": "A", "fuente": {"carpeta": "/m"}, "color": "rojo"}, "color"),
    ({"nombre": "A", "fuente": {"carpeta": "/m"}, "dj": {"idioma": "fr"}}, "idioma"),
    ({"nombre": "A", "fuente": {"carpeta": "/m"}, "dj": "af_heart"}, "dj"),
    ("Lentos", "objeto"),
])
def test_errores_de_una_emisora(tmp_path, datos, mensaje):
    with pytest.raises(ErrorConfig, match=mensaje):
        leer_emisoras(escribir(tmp_path, [datos]), ConfigDJ())


def test_el_mensaje_del_dj_dice_que_emisora(tmp_path):
    a = escribir(tmp_path, [{"nombre": "Lentos", "fuente": {"carpeta": "/m"}, "dj": {"idioma": "fr"}}])
    with pytest.raises(ErrorConfig, match=r'estaciones\.json.*"Lentos".*idioma'):
        leer_emisoras(a, ConfigDJ())


def test_nombres_repetidos_sin_importar_mayusculas(tmp_path):
    a = escribir(tmp_path, [{"nombre": "Lentos", "fuente": {"carpeta": "/a"}},
                            {"nombre": "lentos", "fuente": {"carpeta": "/b"}}])
    with pytest.raises(ErrorConfig, match="repetid"):
        leer_emisoras(a, ConfigDJ())


def test_json_roto_dice_la_linea(tmp_path):
    a = tmp_path / "estaciones.json"
    a.write_text('[\n  {"nombre": "A", "fuente": {"carpeta": "/m"}},\n]\n')
    with pytest.raises(ErrorConfig, match=r"estaciones\.json.*l[ií]nea 3"):
        leer_emisoras(a, ConfigDJ())


def test_la_raiz_tiene_que_ser_una_lista(tmp_path):
    with pytest.raises(ErrorConfig, match="lista"):
        leer_emisoras(escribir(tmp_path, {"nombre": "A"}), ConfigDJ())


def test_archivo_ilegible_es_error_de_config(tmp_path):
    with pytest.raises(ErrorConfig, match="estaciones"):
        leer_emisoras(tmp_path / "estaciones.json", ConfigDJ())


# --- migración ---

def test_migra_las_carpetas_con_sus_ajustes(tmp_path, crear_mp3):
    musica = tmp_path / "Música"
    crear_mp3(musica / "Power F.M." / "a.mp3")
    crear_mp3(musica / "Happy Eighties" / "b.mp3")
    toml = tmp_path / "config.toml"
    toml.write_text('[dj]\nactivo = true\n[dj.estaciones."Power F.M."]\nidioma = "en"\nvoz = "am_onyx"\n'
                    '[dj.estaciones."Power F.M.".frecuencia]\nmin = 1\nmax = 1\n')
    archivo = tmp_path / "estaciones.json"
    assert migrar_emisoras(archivo, musica, toml) is True
    assert json.loads(archivo.read_text()) == [
        {"nombre": "Happy Eighties", "fuente": {"carpeta": str(musica / "Happy Eighties")}},
        {"nombre": "Power F.M.", "fuente": {"carpeta": str(musica / "Power F.M.")},
         "dj": {"idioma": "en", "voz": "am_onyx", "frecuencia": {"min": 1, "max": 1}}}]
    (_, power) = leer_emisoras(archivo, ConfigDJ())
    assert power.dj.voz == "am_onyx" and power.dj.frecuencia.max == 1


def test_no_pisa_un_json_existente(tmp_path, crear_mp3):
    crear_mp3(tmp_path / "m" / "A" / "a.mp3")
    archivo = tmp_path / "estaciones.json"
    archivo.write_text("[]")
    assert migrar_emisoras(archivo, tmp_path / "m", tmp_path / "c.toml") is False
    assert archivo.read_text() == "[]"


def test_sin_carpetas_no_escribe(tmp_path):
    archivo = tmp_path / "estaciones.json"
    (tmp_path / "vacia").mkdir()
    assert migrar_emisoras(archivo, tmp_path / "vacia", tmp_path / "c.toml") is False
    assert migrar_emisoras(archivo, tmp_path / "no-existe", tmp_path / "c.toml") is False
    assert not archivo.exists()


def test_sin_toml_migra_sin_dj(tmp_path, crear_mp3):
    crear_mp3(tmp_path / "m" / "A" / "a.mp3")
    archivo = tmp_path / "estaciones.json"
    assert migrar_emisoras(archivo, tmp_path / "m", tmp_path / "no-existe.toml") is True
    assert json.loads(archivo.read_text()) == [{"nombre": "A", "fuente": {"carpeta": str(tmp_path / "m" / "A")}}]


def test_ajustes_de_una_estacion_sin_carpeta_avisan(tmp_path, crear_mp3, caplog):
    crear_mp3(tmp_path / "m" / "A" / "a.mp3")
    toml = tmp_path / "c.toml"
    toml.write_text('[dj.estaciones."Vieja"]\nvoz = "am_puck"\n')
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        migrar_emisoras(tmp_path / "estaciones.json", tmp_path / "m", toml)
    assert "Vieja" in caplog.text
