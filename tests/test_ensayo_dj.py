import importlib.util
import json
from pathlib import Path

from cassette_fm.biblioteca import Estacion, Pista

_RUTA = Path(__file__).resolve().parent.parent / "scripts" / "herramientas" / "ensayo-dj.py"
_spec = importlib.util.spec_from_file_location("ensayo_dj", _RUTA)
ensayo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ensayo)


def test_clasifica_llm_aceptado_descartado_y_plantilla():
    assert ensayo.clasificar({"fuente": "llm", "texto": "x"}) == "ok"
    assert ensayo.clasificar({"fuente": "llm", "descartado": True, "motivo": "vacío"}) == "descartado"
    assert ensayo.clasificar({"fuente": "plantilla", "motivo": "no hay LLM"}) == "plantilla"
    assert ensayo.clasificar({"fuente": "plantilla", "descartado": True}) == "descartado"


def test_la_linea_lleva_hora_estacion_texto_y_motivo_con_colores_distintos():
    r = {"ts": "2026-11-14T12:50:07-03:00", "estacion": "Power F.M.", "voz": "am_onyx", "fuente": "llm",
         "descartado": True, "motivo": "número que no está en los hechos", "crudo": "It was 1981.", "intento": 2}
    plano = ensayo.linea_guion(r, color=False)
    assert "12:50:07" in plano and "Power F.M." in plano and "It was 1981." in plano
    assert "[descartado: número que no está en los hechos]" in plano and "\033" not in plano
    con = ensayo.linea_guion(r, color=True)
    assert "\033[31m" in con and "\033[36m12:50:07" in con                      # rojo el descartado, cian la hora
    ok = ensayo.linea_guion({**r, "descartado": False, "texto": "Bien."}, color=True)
    pl = ensayo.linea_guion({"ts": r["ts"], "fuente": "plantilla", "texto": "Ahora suena."}, color=True)
    assert "\033[32m" in ok and "\033[33m" in pl and "\033[31m" not in pl


def test_el_resumen_cuenta_por_estacion_y_agrupa_motivos():
    registros = [
        {"estacion": "A", "fuente": "llm", "texto": "x"},
        {"estacion": "A", "fuente": "llm", "descartado": True, "motivo": "nombre propio que no está en los hechos: X"},
        {"estacion": "A", "fuente": "llm", "descartado": True, "motivo": "nombre propio que no está en los hechos: Y"},
        {"estacion": "B", "fuente": "plantilla", "motivo": "vacío", "texto": "z"},
    ]
    r = ensayo.resumir(registros)
    assert r["por_estacion"] == {"A": {"ok": 1, "descartado": 2}, "B": {"plantilla": 1}}
    assert r["motivos"][0] == (("descartado", "nombre propio que no está en los hechos"), 2)
    assert (("plantilla", "vacío"), 1) in r["motivos"]


def test_el_seguidor_solo_devuelve_lo_nuevo_y_completo_de_su_pedido(tmp_path):
    log = tmp_path / "guiones.jsonl"
    log.write_text(json.dumps({"id": "viejo", "texto": "a"}) + "\n")
    seg = ensayo.Seguidor(log)
    assert seg.nuevos("viejo") == []                                             # lo anterior al ensayo no cuenta
    with open(log, "a") as f:
        f.write(json.dumps({"id": "e1", "texto": "uno"}) + "\n" + json.dumps({"id": "otro", "texto": "x"}) + "\n")
        f.write('{"id": "e1", "tex')                                             # línea a medio escribir
    assert [r["texto"] for r in seg.nuevos("e1")] == ["uno"]
    with open(log, "a") as f:
        f.write('to": "dos"}\n')
    assert [r["texto"] for r in seg.nuevos("e1")] == ["dos"]


def test_los_pares_son_consecutivos_y_saltean_temas_sin_nombre():
    pistas = tuple(Pista(ruta=Path(f"/m/{i}.mp3"), duracion=100.0 + i, titulo=f"t{i}",
                         artista=None if i == 2 else f"a{i}", cancion=f"c{i}") for i in range(6))
    pares = ensayo.armar_pares(Estacion("E", pistas), 3, 1_800_000_000.0)
    assert len(pares) == 3
    assert all(s.artista for _, s in pares) and all(a is not s for a, s in pares)


def test_una_frase_recortada_se_marca():
    r = {"ts": "2026-11-14T12:50:07-03:00", "fuente": "llm", "texto": "Bien.", "recortado": "número que no está"}
    assert "[llm, recortada: número que no está]" in ensayo.linea_guion(r, color=False)


def test_las_emisoras_y_sus_voces_salen_de_estaciones_json(tmp_path, crear_mp3):
    from cassette_fm.config import Config, Rutas
    crear_mp3(tmp_path / "afuera" / "a.mp3", artista="X", titulo="Y")
    rutas = Rutas(config=tmp_path / "cfg" / "config.toml", estado=tmp_path / "e.json",
                  cache=tmp_path / "d.json", runtime=tmp_path)
    rutas.emisoras.parent.mkdir(parents=True)
    rutas.emisoras.write_text(json.dumps([{"nombre": "Afuera", "fuente": {"carpeta": str(tmp_path / "afuera")},
                                           "dj": {"voz": "am_onyx"}}]))
    estaciones, configuracion = ensayo.cargar_emisoras(Config(raiz_musica=tmp_path / "nada"), rutas)
    assert [e.nombre for e in estaciones] == ["Afuera"]
    assert configuracion("Afuera").voz == "am_onyx"
