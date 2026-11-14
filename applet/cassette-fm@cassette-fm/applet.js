// Applet de Cinnamon para cassette-fm: cliente liviano de la API local del servicio.
// Todo texto y todo detalle del protocolo HTTP viven en logic.js (probado con Node).
const Applet = imports.ui.applet;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
const Mainloop = imports.mainloop;
const ByteArray = imports.byteArray;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;

const UUID = "cassette-fm@cassette-fm";
// El módulo del applet todavía no está registrado mientras se evalúa este archivo: se resuelve en main().
let AppletDir = null;

const INTERVALO_SEGUNDOS = 2;
const TIMEOUT_MS = 3000;
const ESPERA_RUEDA_MS = 150;

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
}

function main(metadata, orientation, panelHeight, instanceId) {
    AppletDir = imports.ui.appletManager.applets[UUID];
    return new CassetteApplet(metadata, orientation, panelHeight, instanceId);
}
