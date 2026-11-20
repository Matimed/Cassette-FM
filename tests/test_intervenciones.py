import json
from dataclasses import replace
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


def test_quitar_estacion_quita_y_borra_sus_clips(entorno):
    nuevo, iv, _, archivo, clips = entorno
    r = nuevo()
    a1, a2 = iv("A", 1100, 10), iv("A", 1200, 10)
    b = iv("B", 1100, 10)
    fuera = iv("A", 1300, 10, nombre="afuera.wav", dentro=False)
    for i in (a1, a2, b, fuera):
        r.agregar(i)
    quitadas = r.quitar_estacion("A")
    assert sorted(i.id for i in quitadas) == sorted([a1.id, a2.id, fuera.id])
    assert r.todas() == [b]
    assert not a1.audio.exists() and not a2.audio.exists()
    assert fuera.audio.exists() and b.audio.exists()      # el de fuera de dir_clips no se toca
    assert nuevo().todas() == [b]                           # persistido


def test_quitar_estacion_sin_intervenciones_no_hace_nada(entorno):
    nuevo, iv, _, archivo, _ = entorno
    r = nuevo()
    b = iv("B", 1100, 10)
    r.agregar(b)
    assert r.quitar_estacion("A") == []
    assert r.todas() == [b] and b.audio.exists()


def test_intervencion_vieja_sin_peticion_carga(entorno):
    nuevo, iv, _, archivo, _ = entorno
    r = nuevo()
    r.agregar(iv("E", 2000.0, 5.0))
    datos = json.loads(archivo.read_text())
    for d in datos:
        d.pop("peticion", None)
    archivo.write_text(json.dumps(datos))
    assert [i.peticion for i in nuevo().todas()] == [None]


def test_quitar_estacion_salvo_peticiones(entorno):
    nuevo, iv, _, _, _ = entorno
    r = nuevo()
    normal = iv("E", 2000.0, 5.0)
    pedida = replace(iv("E", 3000.0, 5.0), peticion="antes")
    r.agregar(normal)
    r.agregar(pedida)
    assert r.quitar_estacion("E", salvo_peticiones=True) == [normal]
    assert r.todas() == [pedida] and nuevo().todas() == [pedida]
    assert not normal.audio.exists() and pedida.audio.exists()


def test_corte_origen_y_posicion_van_y_vuelven_por_el_json(entorno):
    nuevo, iv, _, _, _ = entorno
    r = nuevo()
    i = replace(iv("A", 1100, 10), corte=1105.0, pista_origen="/m/origen.mp3", posicion="entre")
    r.agregar(i)
    (vuelta,) = nuevo().todas()
    assert vuelta == i
    assert (vuelta.corte, vuelta.pista_origen, vuelta.posicion) == (1105.0, "/m/origen.mp3", "entre")


def test_una_intervencion_guardada_sin_los_campos_nuevos_carga_como_inicio(entorno):
    nuevo, iv, _, archivo, _ = entorno
    r = nuevo()
    r.agregar(iv("A", 1100, 10))
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    for d in datos:
        for campo in ("corte", "pista_origen", "posicion"):
            d.pop(campo, None)
    archivo.write_text(json.dumps(datos), encoding="utf-8")
    (i,) = nuevo().todas()
    assert i.corte is None and i.pista_origen is None and i.posicion == "inicio"


def test_una_posicion_invalida_guardada_carga_como_inicio(entorno):
    nuevo, iv, _, archivo, _ = entorno
    nuevo().agregar(iv("A", 1100, 10))
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    datos[0]["posicion"] = "medio"
    archivo.write_text(json.dumps(datos), encoding="utf-8")
    assert nuevo().todas()[0].posicion == "inicio"


def test_corte_estimado_usa_el_corte_o_resta_el_retraso(entorno):
    _, iv, _, _, _ = entorno
    sin_corte = iv("A", 1100, 10)
    assert sin_corte.corte_estimado(1.0) == 1099.0
    assert replace(sin_corte, corte=1103.5).corte_estimado(1.0) == 1103.5


def test_los_campos_nuevos_no_cambian_inicio_fin_ni_el_solape(entorno):
    nuevo, iv, _, _, _ = entorno
    r = nuevo()
    a = replace(iv("A", 1100, 10), corte=1105.0, pista_origen="/m/o.mp3", posicion="entre")
    r.agregar(a)
    assert a.fin == 1110 and r.activa("A", 1109.9) == a and r.activa("A", 1110) is None
    with pytest.raises(ValueError):
        r.agregar(replace(iv("A", 1105, 10), corte=1110.0, posicion="inicio"))
