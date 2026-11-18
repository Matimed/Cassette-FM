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


def test_el_dial_no_usa_keyval_name():
    # el Clutter de Cinnamon 6.4 no tiene keyval_name: cada tecla tiraba un TypeError y el dial no respondía
    assert "keyval_name" not in _js() and "Clutter.KEY_Escape" in _js()


def test_el_dial_arma_el_cierre_antes_de_pedir_el_estado():
    js = _js()
    constructor = js[js.index("class Dial {"):]
    constructor = constructor[:constructor.index("\n    }\n")]
    assert constructor.index("this._reiniciarCierre(") < constructor.index('applet._pedir("GET", "/estado"')


def test_pedir_no_se_traga_los_errores_del_callback():
    assert "global.logError(" in _cuerpo(_js(), "_pedirHttp(host, puerto, token, metodo, ruta, cuerpo, callback)")


def test_la_fila_del_dial_se_difumina_hacia_los_costados():
    js = _js()
    assert "Clutter.ShaderEffect" in js and "smoothstep" in js and "this._fila.add_effect(" in js


def test_el_dial_se_cierra_solo_a_los_3_s_y_con_enter():
    js = _js()
    assert "const DIAL_CIERRE_MS = 3000;" in js
    assert "Clutter.KEY_Return" in js and "Clutter.KEY_KP_Enter" in js


def test_el_dial_tiene_una_escala_y_muestra_solo_el_volumen():
    js = _js()
    assert re.search(r"const DIAL_ESCALA = [\d.]+;", js) and "this._tira.set_scale(DIAL_ESCALA, DIAL_ESCALA)" in js
    assert "◀ ▶ emisora" not in js       # sin la línea de ayuda: en ese renglón, solo el volumen



def test_la_barra_de_volumen_del_dial_se_lee_bien():
    js = _js()
    estilo = js[js.index("this._ayuda = new St.Label("):]
    estilo = estilo[:estilo.index("});")]
    assert "font-size: 1.25em" in estilo and "rgba(255,255,255,0.8)" in estilo


def test_el_dial_no_muestra_la_cancion():
    assert "this._pista" not in _js()


def test_el_applet_tiene_los_ajustes_del_modo_remoto():
    schema = json.loads((CARPETA / "settings-schema.json").read_text(encoding="utf-8"))
    assert schema["is_remote"]["type"] == "switch" and schema["is_remote"]["default"] is False
    assert schema["server_url"]["type"] == "entry" and schema["server_url"]["default"] == ""
    assert schema["server_token"]["type"] == "entry" and schema["server_token"]["default"] == ""


def test_el_receptor_viaja_con_el_applet_y_se_corre_con_python3_y_la_clave_por_entorno():
    js = _js()
    assert (CARPETA / "lan_receiver.py").is_file()
    assert "lan_receiver.py" in js and '"python3"' in js
    assert "setenv" in js and "CASSETTE_LAN_TOKEN" in js
    assert "--token" not in js and "Bearer" not in js          # la clave no va por argumentos ni se arma acá


def test_pedir_decide_entre_el_servicio_local_y_la_radio_remota():
    js = _js()
    cuerpo = js[js.index("    _pedir(metodo, ruta, cuerpo, callback) {"):]
    cuerpo = cuerpo[:cuerpo.index("\n    }\n")]
    assert "this.is_remote" in cuerpo and "_pedirRemoto" in cuerpo


def test_en_modo_remoto_no_se_ofrece_nueva_emisora():
    js = _js()
    menu = js[js.index("    _reconstruirMenu() {"):]
    menu = menu[:menu.index("\n    }\n")]
    assert "this.is_remote" in menu and "Nueva emisora…" in menu
    assert menu.index("this.is_remote") < menu.index("Nueva emisora…")


def test_en_modo_remoto_los_logos_se_bajan_con_el_receptor_cuando_cambia_la_lista_y_no_antes():
    js = _js()
    assert '"icons"' in js and "parsearIconos" in js and "_iconosLocales" in js
    cuerpo = js[js.index("    _actualizarIconos("):]
    cuerpo = cuerpo[:cuerpo.index("\n    }\n")]
    assert "_firmaIconos" in cuerpo and "_iconosReintento" in cuerpo    # solo si cambió, y sin martillar si falla


def test_al_cambiar_o_apagar_el_modo_remoto_se_corta_la_escucha_y_al_quitar_el_applet_tambien():
    js = _js()
    cambio = js[js.index("    _alCambiarRemoto() {"):]
    cambio = cambio[:cambio.index("\n    }\n")]
    assert '"off"' in cambio and "_receptor.escuchando" in cambio
    quitado = js[js.index("    on_applet_removed_from_panel() {"):]
    quitado = quitado[:quitado.index("\n    }\n")]
    assert "this.is_remote" in quitado and '"off"' in quitado
