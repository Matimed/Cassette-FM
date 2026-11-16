// Applet de Cinnamon para cassette-fm: cliente liviano de la API local del servicio.
// Todo texto y todo detalle del protocolo HTTP viven en logic.js (probado con Node).
const Applet = imports.ui.applet;
const ModalDialog = imports.ui.modalDialog;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
const Mainloop = imports.mainloop;
const ByteArray = imports.byteArray;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const St = imports.gi.St;

const UUID = "cassette-fm@cassette-fm";
// El módulo del applet todavía no está registrado mientras se evalúa este archivo: se resuelve en main().
let AppletDir = null;

const INTERVALO_SEGUNDOS = 2;
const TIMEOUT_MS = 3000;
const ESPERA_RUEDA_MS = 150;
const LIMITE_VOCES_SEGUNDOS = 30;
// `cassette nueva` espera el rescan de la radio hasta 120 s después de guardar: cortarlo antes la deja guardada sin avisar
const LIMITE_NUEVA_SEGUNDOS = 180;
const LIMITE_MUESTRA_SEGUNDOS = 60;         // la primera muestra espera que el servicio DJ cargue el modelo
const LIMITE_SONANDO_SEGUNDOS = 120;

class CassetteApplet extends Applet.TextIconApplet {
    constructor(metadata, orientation, panelHeight, instanceId) {
        super(orientation, panelHeight, instanceId);
        this.estado = null;
        this._firmaMenu = null;
        this._limitador = AppletDir.logic.crearLimitador(ESPERA_RUEDA_MS);
        this._sondeando = false;

        this.set_applet_icon_symbolic_name("audio-x-generic-symbolic");

        this.settings = new Settings.AppletSettings(this, metadata.uuid, instanceId);
        this.settings.bind("puerto", "puerto", () => this._sondear());
        this.settings.bind("mostrar_estacion", "mostrar_estacion", () => this._aplicar(this.estado));

        this._seccionEstaciones = new PopupMenu.PopupMenuSection();
        this._applet_context_menu.addMenuItem(this._seccionEstaciones, 0);

        // La clase base Applet de Cinnamon no atiende la rueda por su cuenta: se conecta la señal del actor.
        this.actor.connect("scroll-event", (actor, event) => this._alRueda(event));

        this._aplicar(null);
        this._sondear();
        this._temporizador = Mainloop.timeout_add_seconds(INTERVALO_SEGUNDOS, () => {
            this._sondear();
            return true;
        });
    }

    on_applet_clicked(event) {
        this._accion("/alternar");
    }

    _alRueda(event) {
        const direccion = event.get_scroll_direction();
        // Los touchpads emiten SMOOTH (con deltas): no se interpretan, se deja pasar el evento.
        if (direccion === Clutter.ScrollDirection.SMOOTH) return Clutter.EVENT_PROPAGATE;
        let nombre = null;
        if (direccion === Clutter.ScrollDirection.UP) nombre = "up";
        else if (direccion === Clutter.ScrollDirection.DOWN) nombre = "down";
        const accion = AppletDir.logic.accionDeRueda(nombre);
        if (accion === null) return Clutter.EVENT_PROPAGATE;
        if (this._limitador(Date.now())) this._accion("/" + accion);
        return Clutter.EVENT_STOP;
    }

    on_applet_removed_from_panel() {
        if (this._temporizador) {
            Mainloop.source_remove(this._temporizador);
            this._temporizador = 0;
        }
        this.settings.finalize();
    }

    _sondear() {
        if (this._sondeando) return;
        this._sondeando = true;
        this._pedir("GET", "/estado", undefined, (r) => {
            this._sondeando = false;
            this._aplicar(r.codigo === 200 ? r.datos : null);
        });
    }

    _accion(ruta, cuerpo) {
        this._pedir("POST", ruta, cuerpo, (r) => {
            if (r.codigo === 200) {
                this._aplicar(r.datos);
            } else {
                if (r.datos && r.datos.error) global.logWarning("cassette-fm: " + r.datos.error);
                this._sondear();
            }
        });
    }

    _aplicar(estado) {
        this.estado = estado;
        this.set_applet_label(AppletDir.logic.etiqueta(estado, this.mostrar_estacion));
        this.set_applet_tooltip(AppletDir.logic.tooltip(estado));
        this._reconstruirMenu();
    }

    _reconstruirMenu() {
        const estado = this.estado;
        const firma = estado ? JSON.stringify([estado.estaciones, estado.estacion, estado.encendida]) : "";
        if (firma === this._firmaMenu) return;
        this._firmaMenu = firma;
        this._seccionEstaciones.removeAll();
        if (!estado) return;
        for (const nombre of estado.estaciones) {
            const actual = estado.encendida && nombre === estado.estacion;
            const item = new PopupMenu.PopupMenuItem((actual ? "▶ " : "    ") + nombre);
            item.connect("activate", () => this._accion("/sintonizar", { estacion: nombre }));
            this._seccionEstaciones.addMenuItem(item);
        }
        const nueva = new PopupMenu.PopupMenuItem("    Nueva emisora…");
        nueva.connect("activate", () => new DialogoEmisora(this).abrir());
        this._seccionEstaciones.addMenuItem(nueva);
        if (estado.encendida) {
            const apagar = new PopupMenu.PopupMenuItem("Apagar");
            apagar.connect("activate", () => this._accion("/apagar"));
            this._seccionEstaciones.addMenuItem(apagar);
        }
        this._seccionEstaciones.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    }

    // HTTP por un socket de GIO, todo asíncrono; cualquier error termina en callback({codigo: 0}).
    _pedir(metodo, ruta, cuerpo, callback) {
        const cancelable = new Gio.Cancellable();
        let terminado = false;
        const terminar = (texto, vencio) => {
            if (terminado) return;
            terminado = true;
            if (!vencio) Mainloop.source_remove(vencimiento);
            callback(AppletDir.logic.parsearRespuesta(texto));
        };
        const vencimiento = Mainloop.timeout_add(TIMEOUT_MS, () => {
            cancelable.cancel();
            terminar(null, true);
            return false;
        });
        try {
            new Gio.SocketClient().connect_to_host_async("127.0.0.1:" + this.puerto, 0, cancelable,
                (cliente, resultado) => {
                    try {
                        const conexion = cliente.connect_to_host_finish(resultado);
                        const entrada = conexion.get_input_stream();
                        const salida = new Gio.DataOutputStream({ base_stream: conexion.get_output_stream() });
                        salida.put_string(AppletDir.logic.pedidoHttp(metodo, ruta, cuerpo), cancelable);
                        salida.flush(cancelable);
                        const memoria = Gio.MemoryOutputStream.new_resizable();
                        memoria.splice_async(entrada,
                            Gio.OutputStreamSpliceFlags.CLOSE_SOURCE | Gio.OutputStreamSpliceFlags.CLOSE_TARGET,
                            GLib.PRIORITY_DEFAULT, cancelable, (flujo, res) => {
                                try {
                                    flujo.splice_finish(res);
                                    terminar(ByteArray.toString(ByteArray.fromGBytes(flujo.steal_as_bytes())));
                                } catch (e) {
                                    terminar(null);
                                }
                                conexion.close_async(GLib.PRIORITY_DEFAULT, null, null);
                            });
                    } catch (e) {
                        terminar(null);
                    }
                });
        } catch (e) {
            terminar(null);
        }
    }

    // Corre `<programa> <argumentos>` sin shell y sin bloquear el panel; callback({codigo, stdout, stderr}) o
    // callback({error}) si no se encuentra, no arranca o pasa el límite (y entonces se lo corta). Devuelve el
    // proceso (para cortarlo con force_exit) o null si no arrancó.
    _correr(programa, argumentos, segundos, callback) {
        let ruta = GLib.find_program_in_path(programa);
        const local = GLib.get_home_dir() + "/.local/bin/" + programa;
        if (!ruta && GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE)) ruta = local;
        if (!ruta) {
            callback({ error: "No encuentro el comando " + programa + " (¿está instalado?)" });
            return null;
        }
        let terminado = false;
        let vencimiento = 0;
        const terminar = (resultado) => {
            if (terminado) return;
            terminado = true;
            if (vencimiento) Mainloop.source_remove(vencimiento);
            callback(resultado);
        };
        let proceso;
        try {
            proceso = Gio.Subprocess.new([ruta, ...argumentos],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        } catch (e) {
            callback({ error: "No pude correr " + programa + ": " + e.message });
            return null;
        }
        vencimiento = Mainloop.timeout_add_seconds(segundos, () => {
            vencimiento = 0;
            proceso.force_exit();
            terminar({ error: programa + " tardó más de " + segundos + " s: se cortó" });
            return false;
        });
        proceso.communicate_utf8_async(null, null, (p, res) => {
            try {
                const [, stdout, stderr] = p.communicate_utf8_finish(res);
                terminar({ codigo: p.get_exit_status(), stdout: stdout, stderr: stderr });
            } catch (e) {
                terminar({ error: "No pude leer lo que contestó " + programa + ": " + e.message });
            }
        });
        return proceso;
    }
}

// El modal de "Nueva emisora…": nombre, playlist, idioma y voz; crea la emisora con `cassette nueva`.
// Compone un ModalDialog en vez de heredarlo: una subclase GObject no se puede volver a registrar al recargar el applet.
class DialogoEmisora {
    constructor(applet) {
        this._applet = applet;
        this._voces = [];
        this._seleccion = { idioma: "", voz: null };
        this._cerrado = false;
        this._fase = "quieto";          // de la muestra de voz: quieto, generando o sonando
        this._muestra = 0;              // cuál es la muestra vigente: la respuesta de una ya cortada no cambia nada
        this._proceso = null;
        this._dialogo = new ModalDialog.ModalDialog({ destroyOnClose: true });
        const caja = this._dialogo.contentLayout;
        caja.set_style("width: 30em; spacing: 8px;");

        caja.add_child(new St.Label({ text: "Emisora nueva", style: "font-weight: bold; font-size: 1.2em;" }));
        const fila = (titulo, ...hijos) => {
            const caja = new St.BoxLayout({ style: "spacing: 6px;" });
            caja.add_child(new St.Label({ text: titulo, y_align: Clutter.ActorAlign.CENTER, style: "width: 4em;" }));
            for (const hijo of hijos) caja.add_child(hijo);
            return caja;
        };
        const campo = (pista) => new St.Entry({ style_class: "run-dialog-entry", hint_text: pista, can_focus: true,
                                               x_expand: true });
        this._nombre = campo("Synthwave F.M.");
        this._link = campo("https://open.spotify.com/playlist/…");
        caja.add_child(fila("Nombre", this._nombre));
        caja.add_child(fila("Playlist", this._link));
        for (const campo of [this._nombre, this._link]) campo.clutter_text.connect("activate", () => this._alEnter());

        const filaIdioma = fila("Idioma");
        this._botonesIdioma = [["", "Cualquiera"], ["es", "Español"], ["en", "Inglés"]].map(([idioma, texto]) => {
            const boton = new St.Button({ label: texto, style_class: "dialog-button", can_focus: true });
            boton.connect("clicked", () => this._alElegirIdioma(idioma));
            boton._texto = texto;
            boton._idioma = idioma;
            filaIdioma.add_child(boton);
            return boton;
        });
        caja.add_child(filaIdioma);

        this._botonVoz = new St.Button({ style_class: "dialog-button", can_focus: true, x_expand: true });
        this._botonVoz.connect("clicked", () => this._desplegar(!this._lista.visible));
        this._botonMuestra = new St.Button({ style_class: "dialog-button", can_focus: true });
        this._botonMuestra.connect("clicked", () => this._alMuestra());
        caja.add_child(fila("Voz", this._botonVoz, this._botonMuestra));

        // El desplegable: una lista con scroll dentro del diálogo (el combo de Cinnamon solo anda dentro de un menú).
        this._opciones = new St.BoxLayout({ vertical: true });
        this._lista = new St.ScrollView({ hscrollbar_policy: St.PolicyType.NEVER,
                                          vscrollbar_policy: St.PolicyType.AUTOMATIC,
                                          style: "max-height: 200px; margin-left: 4.5em;" });
        this._lista.add_actor(this._opciones);
        this._lista.hide();
        caja.add_child(this._lista);

        this._error = new St.Label({ style: "color: #e66;" });
        this._error.clutter_text.line_wrap = true;
        this._error.hide();
        caja.add_child(this._error);

        this._cancelar = this._dialogo.addButton({ label: "Cancelar", action: () => this._cerrar(),
                                                   key: Clutter.KEY_Escape });
        this._crear = this._dialogo.addButton({ label: "Crear", action: () => this._alCrear(), default: true });
        this._dialogo.setInitialKeyFocus(this._nombre);
        this._refrescar();
    }

    abrir() {
        this._dialogo.open();
        this._applet._correr("cassette", ["voces", "--json"], LIMITE_VOCES_SEGUNDOS, (r) => {
            if (this._cerrado) return;
            const voces = r.error || r.codigo !== 0 ? null : AppletDir.logic.parsearVoces(r.stdout);
            if (voces === null) {
                const motivo = r.error || (r.codigo !== 0 ? AppletDir.logic.mensajeDeError(r.codigo, "", r.stderr)
                                                          : "cassette voces no contestó una lista de voces");
                this._mostrarError("No pude leer las voces: " + motivo);
                return;
            }
            this._voces = voces;
            this._refrescar();
        });
    }

    _cerrar() {
        this._cortarMuestra();
        this._cerrado = true;
        this._dialogo.close();
    }

    _alElegirIdioma(idioma) {
        this._seleccion = AppletDir.logic.elegirIdioma(this._seleccion, idioma);
        this._refrescar();
    }

    _alElegirVoz(voz) {
        this._cortarMuestra();
        this._seleccion = AppletDir.logic.elegirVoz(this._seleccion, voz);
        this._desplegar(false);
        this._refrescar();
    }

    _desplegar(abierto) {
        if (abierto) this._lista.show();
        else this._lista.hide();
        this._refrescar();
    }

    _refrescar() {
        for (const boton of this._botonesIdioma) {
            const elegido = boton._idioma === this._seleccion.idioma;
            boton.label = (elegido ? "● " : "") + boton._texto;
            if (elegido) boton.add_style_pseudo_class("checked");
            else boton.remove_style_pseudo_class("checked");
        }
        this._botonVoz.label = AppletDir.logic.etiquetaDeVoz(this._seleccion.voz)
            + (this._lista.visible ? "  ▴" : "  ▾");
        this._opciones.destroy_all_children();
        for (const voz of [null, ...AppletDir.logic.vocesDelIdioma(this._voces, this._seleccion.idioma)]) {
            const opcion = new St.Button({ label: AppletDir.logic.etiquetaDeVoz(voz), x_align: St.Align.START,
                                           x_fill: false, track_hover: true, can_focus: true,
                                           style: "padding: 4px 8px;" });
            opcion.connect("notify::hover", () =>
                opcion.set_style("padding: 4px 8px;" + (opcion.hover ? " background-color: rgba(128,128,128,0.3);" : "")));
            opcion.connect("clicked", () => this._alElegirVoz(voz));
            this._opciones.add_child(opcion);
        }
        const muestra = AppletDir.logic.botonMuestra(this._seleccion.voz, this._fase);
        this._botonMuestra.label = muestra.texto;
        this._botonMuestra.reactive = muestra.activo;
    }

    // ▶: la voz elegida dice "Hola, soy … y estás escuchando <nombre>" (`cassette-dj muestra`, después mpv); ■ la corta.
    _alMuestra() {
        if (this._fase === "sonando") {
            this._cortarMuestra();
            return;
        }
        const voz = this._seleccion.voz;
        if (this._fase !== "quieto" || !voz) return;
        const n = ++this._muestra;
        this._error.hide();
        this._fase = "generando";
        this._refrescar();
        const argumentos = AppletDir.logic.argumentosMuestra(voz, this._nombre.get_text());
        this._proceso = this._applet._correr("cassette-dj", argumentos, LIMITE_MUESTRA_SEGUNDOS, (r) => {
            if (n !== this._muestra || this._cerrado) return;
            const ruta = r.error || r.codigo !== 0 ? null : AppletDir.logic.rutaDeMuestra(r.stdout);
            if (!ruta) {
                this._proceso = null;
                this._fase = "quieto";
                this._refrescar();
                const motivo = r.error || (r.codigo !== 0 ? AppletDir.logic.mensajeDeError(r.codigo, r.stdout, r.stderr)
                                                          : "cassette-dj no devolvió el audio");
                this._mostrarError("No pude reproducir la muestra: " + motivo);
                return;
            }
            this._fase = "sonando";
            this._refrescar();
            this._proceso = this._applet._correr("mpv", ["--no-video", "--really-quiet", ruta],
                                                 LIMITE_SONANDO_SEGUNDOS, (s) => {
                if (n !== this._muestra || this._cerrado) return;
                this._proceso = null;
                this._fase = "quieto";
                this._refrescar();
                if (s.error) this._mostrarError("No pude reproducir la muestra: " + s.error);
            });
        });
    }

    _cortarMuestra() {
        this._muestra++;
        if (this._proceso) this._proceso.force_exit();
        this._proceso = null;
        if (this._fase === "quieto") return;
        this._fase = "quieto";
        if (!this._cerrado) this._refrescar();
    }

    _mostrarError(texto) {
        this._error.text = texto;
        this._error.show();
    }

    // Mientras corre `cassette nueva` no se puede tocar nada: lo que se ve es lo que se está creando.
    _ocupado(si) {
        this._cortarMuestra();
        if (si && this._lista.visible) this._desplegar(false);
        this._crear.label = si ? "Creando…" : "Crear";
        // un botón no reactivo tampoco responde a su tecla (Enter, Escape): no hay doble `cassette nueva`
        this._crear.reactive = !si;
        this._cancelar.reactive = !si;
        for (const campo of [this._nombre, this._link]) {
            campo.reactive = !si;
            campo.clutter_text.editable = !si;
        }
        for (const boton of [this._botonVoz, this._botonMuestra, ...this._botonesIdioma,
                             ...this._opciones.get_children()])
            boton.reactive = !si;
        if (!si) this._refrescar();     // el ▶ vuelve a depender de la voz elegida
    }

    // Enter en un campo: el St.Entry se come la tecla y el "default" de Crear no se entera.
    _alEnter() {
        if (this._crear.reactive) this._alCrear();
    }

    _alCrear() {
        const nombre = this._nombre.get_text();
        const link = this._link.get_text();
        const falta = AppletDir.logic.faltante(nombre, link);
        if (falta) {
            this._mostrarError(falta);
            return;
        }
        this._error.hide();
        this._ocupado(true);
        const argumentos = AppletDir.logic.argumentosNueva(nombre, link, this._seleccion);
        this._applet._correr("cassette", argumentos, LIMITE_NUEVA_SEGUNDOS, (r) => {
            if (!r.error && r.codigo === 0) {
                this._cerrar();
                this._applet._sondear();
                return;
            }
            this._ocupado(false);
            this._mostrarError(r.error || AppletDir.logic.mensajeDeError(r.codigo, r.stdout, r.stderr));
        });
    }
}

function main(metadata, orientation, panelHeight, instanceId) {
    AppletDir = imports.ui.appletManager.applets[UUID];
    return new CassetteApplet(metadata, orientation, panelHeight, instanceId);
}
