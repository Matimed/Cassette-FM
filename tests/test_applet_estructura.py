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


def test_la_rueda_se_conecta_a_la_senal_del_actor():
    js = _js()
    # la clase base Applet de Cinnamon 6.4 no llama a on_applet_scrolled: hay que conectar la señal
    assert "scroll-event" in js
    assert "on_applet_scrolled" not in js
    assert "Clutter.ScrollDirection.SMOOTH" in js and "EVENT_PROPAGATE" in js


def test_el_menu_tiene_nueva_emisora_y_corre_cassette_asincrono():
    js = _js()
    assert "Nueva emisora…" in js and "ModalDialog" in js
    assert "Gio.Subprocess" in js and "communicate_utf8_async" in js
    for sincronico in ("spawn_command_line_sync", "communicate_utf8(", ".wait(", "spawn_sync"):
        assert sincronico not in js, sincronico     # el panel nunca se congela


def test_el_modal_no_usa_el_combo_de_cinnamon():
    assert "PopupComboBoxMenuItem" not in _js()     # no funciona dentro de un ModalDialog


def test_el_limite_de_cassette_nueva_cubre_el_rescan_de_la_cli():
    # `cassette nueva` guarda la emisora y después espera el rescan: cortarlo antes la deja guardada sin avisar
    cli = (RAIZ / "src" / "cassette_fm" / "cli.py").read_text(encoding="utf-8")
    rescan = int(re.search(r'"/rescan", timeout=(\d+)', cli).group(1))
    limite = int(re.search(r"LIMITE_NUEVA_SEGUNDOS = (\d+)", _js()).group(1))
    assert limite >= rescan + 60, (limite, rescan)    # más la playlist, la sintonía y el arranque de Python
    assert "LIMITE_NUEVA_SEGUNDOS, (r)" in _js()


def test_enter_en_los_campos_crea():
    # el St.Entry se come el Return: el "default" del botón Crear no se entera
    assert len(re.findall(r'clutter_text\.connect\("activate"', _js())) >= 1
    assert "_alEnter" in _js() and "this._crear.reactive" in _js()


def test_mientras_crea_se_bloquea_todo_el_modal():
    js = _js()
    cuerpo = js[js.index("    _ocupado(si) {"):]
    cuerpo = cuerpo[:cuerpo.index("\n    }\n")]
    for widget in ("this._nombre", "this._link", "this._botonVoz", "this._botonesIdioma", "this._opciones",
                   "this._crear", "this._cancelar"):
        assert widget in cuerpo, widget


def test_el_modal_tiene_muestra_de_voz_y_la_corta():
    js = _js()
    assert "argumentosMuestra" in js and "botonMuestra" in js and "rutaDeMuestra" in js
    assert '"cassette-dj"' in js and '"mpv"' in js
    for donde in ("_cerrar()", "_alElegirVoz(voz)", "_alElegirIdioma(idioma)", "_ocupado(si)"):
        cuerpo = js[js.index("    " + donde + " {"):]
        assert "this._cortarMuestra()" in cuerpo[:cuerpo.index("\n    }\n")], donde


def test_el_modal_elige_el_logo_con_zenity_y_lo_bloquea_al_crear():
    js = _js()
    assert '"zenity"' in js and "argumentosExaminar" in js and "rutaElegida" in js
    cuerpo = js[js.index("    _ocupado(si) {"):]
    cuerpo = cuerpo[:cuerpo.index("\n    }\n")]
    assert "this._botonExaminar" in cuerpo and "this._botonQuitarLogo" in cuerpo


def _cuerpo(js, firma):
    cuerpo = js[js.index("    " + firma + " {"):]
    return cuerpo[:cuerpo.index("\n    }\n")]


def test_el_dial_tiene_su_atajo_y_lo_suelta_al_quitar_el_applet():
    schema = json.loads((CARPETA / "settings-schema.json").read_text(encoding="utf-8"))
    assert schema["atajo_dial"]["type"] == "keybinding" and schema["atajo_dial"]["default"] == "<Super><Alt>space"
    js = _js()
    assert "Main.keybindingManager.addHotKey(" in js
    quitar = _cuerpo(js, "on_applet_removed_from_panel()")
    assert "Main.keybindingManager.removeHotKey(" in quitar and "this._dial" in quitar


def test_el_dial_siempre_suelta_el_teclado_al_cerrarse():
    js = _js()
    assert js.count("Main.pushModal(") == js.count("Main.popModal(") == 1
    assert "Main.popModal(" in _cuerpo(js, "cerrar()")


def test_el_dial_usa_la_logica_probada():
    js = _js()
    for funcion in ("teclaDial", "filaDial", "crearCola", "barraVolumen", "iconoDe"):
        assert f"AppletDir.logic.{funcion}(" in js, funcion
