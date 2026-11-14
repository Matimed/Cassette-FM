import json
from pathlib import Path

import pytest

from cassette_fm.intervenciones import Intervencion, RegistroIntervenciones


class Reloj:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def entorno(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    reloj = Reloj()
    archivo = tmp_path / "estado" / "intervenciones.json"

    def nuevo(gracia=0.0):
        return RegistroIntervenciones(archivo, clips, reloj, gracia_segundos=gracia)

    def iv(estacion, inicio, dur, nombre=None, dentro=True):
        audio = (clips if dentro else tmp_path) / (nombre or f"{estacion}-{inicio}.wav")
        audio.write_bytes(b"x")
        return Intervencion(f"id-{estacion}-{inicio}", estacion, inicio, dur, audio, "texto", "/m/t.mp3")

    return nuevo, iv, reloj, archivo, clips


def test_agregar_persiste_y_se_recarga(entorno):
    nuevo, iv, _, _, _ = entorno
    r = nuevo()
    i = iv("A", 1100, 10)
    r.agregar(i)
    assert nuevo().todas() == [i]


def test_superposicion_en_la_misma_estacion_falla(entorno):
    nuevo, iv, _, _, _ = entorno
    r = nuevo()
    r.agregar(iv("A", 1010, 10))
    with pytest.raises(ValueError):
        r.agregar(iv("A", 1015, 10))
    r.agregar(iv("A", 1020, 10))      # justo al borde: no se pisan
    r.agregar(iv("B", 1010, 10))      # otra estación puede coincidir
    assert len(r.todas()) == 3


def test_activa_incluye_inicio_y_excluye_fin(entorno):
    nuevo, iv, _, _, _ = entorno
    r = nuevo()
    i = iv("A", 1010, 10)
    r.agregar(i)
    assert r.activa("A", 1010) == i and r.activa("A", 1019.9) == i
    assert r.activa("A", 1009.9) is None and r.activa("A", 1020) is None
    assert r.activa("B", 1015) is None


def test_de_la_estacion_filtra_vigentes_y_ordena(entorno):
    nuevo, iv, reloj, _, _ = entorno
    r = nuevo()
    tarde, temprano, pasada = iv("A", 1100, 5), iv("A", 1050, 5), iv("A", 1000, 5)
    for i in (tarde, temprano, pasada):
        r.agregar(i)
    reloj.t = 1010
    assert r.de_la_estacion("A") == [temprano, tarde]


def test_limpiar_quita_vencidas_y_borra_sus_clips(entorno):
    nuevo, iv, reloj, archivo, _ = entorno
    r = nuevo()
    vieja, nueva = iv("A", 1010, 10), iv("A", 1100, 10)
    r.agregar(vieja)
    r.agregar(nueva)
    reloj.t = 1020
    assert r.limpiar() == [vieja]
    assert not vieja.audio.exists() and nueva.audio.exists()
    assert [d["id"] for d in json.loads(archivo.read_text())] == [nueva.id]


def test_la_gracia_posterga_la_limpieza_y_define_las_candidatas(entorno):
    nuevo, iv, reloj, _, _ = entorno
    r = nuevo(gracia=10.0)
    i = iv("A", 1010, 10)                                        # fin = 1020
    r.agregar(i)
    reloj.t = 1025
    assert r.limpiar() == [] and r.candidatas("A") == [i] and r.de_la_estacion("A") == []
    reloj.t = 1031
    assert r.candidatas("A") == [] and r.limpiar() == [i]


def test_limpiar_no_borra_archivos_fuera_de_dir_clips(entorno):
    nuevo, iv, reloj, _, _ = entorno
    r = nuevo()
    ajena = iv("A", 1010, 10, nombre="mio.wav", dentro=False)
    r.agregar(ajena)
    reloj.t = 1020
    r.limpiar()
    assert ajena.audio.exists()


def test_json_corrupto_o_ausente_da_registro_vacio(entorno):
    nuevo, _, _, archivo, _ = entorno
    assert nuevo().todas() == []
    archivo.parent.mkdir(parents=True)
    archivo.write_text("{no es json")
    assert nuevo().todas() == []
    archivo.write_text('[{"id": 1}]')     # entrada con campos que faltan
    assert nuevo().todas() == []


def test_al_cargar_descarta_vencidas_y_sin_archivo(entorno):
    nuevo, iv, reloj, _, _ = entorno
    r = nuevo()
    vigente, vencida, sin_clip = iv("A", 1100, 10), iv("A", 1010, 10), iv("B", 1200, 10)
    for i in (vigente, vencida, sin_clip):
        r.agregar(i)
    reloj.t = 1050
    sin_clip.audio.unlink()
    assert nuevo().todas() == [vigente]
