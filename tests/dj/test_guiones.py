import json
import threading
from datetime import datetime

from cassette_fm.dj.guiones import RegistroGuiones


def test_anota_una_linea_json_con_ts_y_acentos(tmp_path):
    g = RegistroGuiones(tmp_path / "guiones.jsonl")
    g.anotar(id="a", texto="Qué tal, gente: Música Ñandú", n=3)
    (linea,) = (tmp_path / "guiones.jsonl").read_text(encoding="utf-8").splitlines()
    d = json.loads(linea)
    assert d["id"] == "a" and d["texto"] == "Qué tal, gente: Música Ñandú" and d["n"] == 3
    assert "Ñandú" in linea                                    # sin escapar a \uXXXX
    assert datetime.fromisoformat(d["ts"]).tzinfo is not None


def test_crea_los_directorios(tmp_path):
    RegistroGuiones(tmp_path / "a" / "b" / "g.jsonl").anotar(x=1)
    assert (tmp_path / "a" / "b" / "g.jsonl").exists()


def test_no_trunca_ni_borra_lo_anterior(tmp_path):
    archivo = tmp_path / "g.jsonl"
    RegistroGuiones(archivo).anotar(n=1)
    RegistroGuiones(archivo).anotar(n=2)                       # una instancia nueva sigue agregando
    assert [json.loads(l)["n"] for l in archivo.read_text().splitlines()] == [1, 2]


def test_desde_varios_hilos_no_mezcla_lineas(tmp_path):
    g = RegistroGuiones(tmp_path / "g.jsonl")

    def escribir(k):
        for i in range(50):
            g.anotar(hilo=k, i=i, texto="x" * 200)

    hilos = [threading.Thread(target=escribir, args=(k,)) for k in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(10)
    lineas = (tmp_path / "g.jsonl").read_text().splitlines()
    assert len(lineas) == 400
    assert len({(json.loads(l)["hilo"], json.loads(l)["i"]) for l in lineas}) == 400


def test_ultimos_devuelve_los_ultimos_en_orden_e_ignora_lineas_rotas(tmp_path):
    archivo = tmp_path / "g.jsonl"
    g = RegistroGuiones(archivo)
    for n in range(5):
        g.anotar(n=n)
    with open(archivo, "a", encoding="utf-8") as f:
        f.write("esto no es json\n")
    g.anotar(n=5)
    assert [d["n"] for d in g.ultimos(3)] == [3, 4, 5]
    assert [d["n"] for d in g.ultimos(100)] == [0, 1, 2, 3, 4, 5]
    assert g.ultimos(0) == []


def test_ultimos_sin_archivo_es_vacio(tmp_path):
    assert RegistroGuiones(tmp_path / "no-existe.jsonl").ultimos(5) == []
