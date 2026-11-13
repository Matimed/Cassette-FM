import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "applet" / "cassette-fm@cassette-fm"


def _js():
    return (CARPETA / "applet.js").read_text(encoding="utf-8")


def test_metadata_coincide_con_la_carpeta():
    meta = json.loads((CARPETA / "metadata.json").read_text(encoding="utf-8"))
    assert meta["uuid"] == "cassette-fm@cassette-fm" == CARPETA.name
    assert meta["max-instances"] == 1


def test_el_applet_solo_usa_funciones_que_logic_exporta():
    exportadas = set(re.findall(r"[\w]+", re.search(
        r"module\.exports\s*=\s*\{([^}]*)\}", (CARPETA / "logic.js").read_text(encoding="utf-8")).group(1)))
    usadas = set(re.findall(r"AppletDir\.logic\.(\w+)", _js()))
    assert usadas, "applet.js no usa logic.js"
    assert usadas <= exportadas, usadas - exportadas


def test_los_ajustes_del_schema_coinciden_con_los_que_el_applet_enlaza():
    schema = json.loads((CARPETA / "settings-schema.json").read_text(encoding="utf-8"))
    enlazados = set(re.findall(r'settings\.bind\("(\w+)"', _js()))
    assert enlazados == set(schema)
    assert schema["puerto"]["default"] == 7710
    assert schema["mostrar_estacion"]["default"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
def test_applet_js_tiene_sintaxis_valida():
    r = subprocess.run(["node", "--check", str(CARPETA / "applet.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_el_applet_no_duplica_la_logica_del_protocolo():
    js = _js()
    assert "HTTP/1.0" not in js and "Content-Length" not in js
    assert "JSON.parse" not in js
