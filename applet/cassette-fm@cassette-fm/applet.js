// Applet de Cinnamon para cassette-fm: cliente liviano de la API local del servicio.
// Todo texto y todo detalle del protocolo HTTP viven en logic.js (probado con Node).
const Applet = imports.ui.applet;
const Main = imports.ui.main;
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
const LIMITE_RECEPTOR_SEGUNDOS = 10;          // lan_receiver.py (modo remoto): prender, apagar, volumen, estado
const RESYNC_ESPERA_MS = 400;               // tras el último cambio de emisora, antes de volver a "en vivo"
const ICONOS_REINTENTO_MS = 30000;          // si bajar los logos falla, no se reintenta antes
const RECEPTOR_AL_DIA_MS = 10000;           // cada cuánto se le pregunta cómo está (se entera de que mpv murió)
const LIMITE_EXAMINAR_SEGUNDOS = 600;       // lo que tarda la persona en elegir la imagen
const BARRAS_COLUMNAS = 4;                  // las barritas de puntos del panel (suena la radio)
const BARRAS_FILAS = 5;
const BARRAS_CUADRO_MS = 90;                // cada cuánto se redibujan (≈ 11 cuadros por segundo)

class CassetteApplet extends Applet.TextIconApplet {
    constructor(metadata, orientation, panelHeight, instanceId) {
        super(orientation, panelHeight, instanceId);
        this.generico = metadata.path + "/generico.png";     // el logo de las emisoras que no tienen uno
        this.estado = null;
        this._firmaMenu = null;
        this._limitador = AppletDir.logic.crearLimitador(ESPERA_RUEDA_MS);
        this._sondeando = false;

        // Apagada: el casete de la marca en blanco y sin fondo (branding/). Con la radio prendida el ícono se cambia por las
        // barritas de puntos blancos, que suben y bajan, y al lado va el nombre de la emisora.
        this.set_applet_icon_path(metadata.path + "/casete-panel.png");
        this._animacionBarras = 0;
        this._barrasT0 = Date.now();
        this._barras = new St.DrawingArea({ visible: false, reactive: false, y_align: Clutter.ActorAlign.CENTER });
        this._barras.set_style("margin: 0 4px;");
        this._barras.connect("repaint", (area) => this._dibujarBarras(area));
        this.actor.insert_child_above(this._barras, this._applet_icon_box);

        this.settings = new Settings.AppletSettings(this, metadata.uuid, instanceId);
        this.settings.bind("puerto", "puerto", () => this._sondear());
        // modo remoto: la radio está en otra PC; acá solo se escucha (lan_receiver.py) y se elige la emisora
        this._dirApplet = metadata.path;
        this._receptor = { escuchando: false, volumen: 70, error: null };
        this._receptorTs = 0;
        this._ultimoStatus = null;
        this._iconosLocales = {};       // {emisora: ruta local} de los logos que publicó la radio remota
        this._firmaIconos = null;
        this._iconosReintento = 0;
        this._resync = 0;               // temporizador del resync tras cambiar de emisora
        this._resincronizando = false;  // el receptor está reconectando
        this.settings.bind("is_remote", "is_remote", () => this._alCambiarRemoto());
        this.settings.bind("server_url", "server_url", () => this._alCambiarRemoto());
        this.settings.bind("server_token", "server_token", () => this._alCambiarRemoto());
        this.settings.bind("mostrar_estacion", "mostrar_estacion", () => this._aplicar(this.estado));
        this._dial = null;
        this._nombreAtajo = "cassette-fm-dial-" + instanceId;
        this.settings.bind("atajo_dial", "atajo_dial", () => this._registrarAtajo());
        this._registrarAtajo();

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

    // El atajo del dial: lo abre, y si está abierto lo cierra (Cinnamon invoca los atajos aunque el dial tenga el
    // teclado tomado).
    _registrarAtajo() {
        Main.keybindingManager.addHotKey(this._nombreAtajo, this.atajo_dial, () => {
            if (this._dial) this._dial.cerrar();
            else this._dial = new Dial(this);
        });
    }

    on_applet_removed_from_panel() {
        if (this._animacionBarras) {
            Mainloop.source_remove(this._animacionBarras);
            this._animacionBarras = 0;
        }
        if (this._resync) Mainloop.source_remove(this._resync);
        if (this.is_remote) this._correrReceptor(["off"], () => {});     // no queda un mpv sonando sin dueño
        Main.keybindingManager.removeHotKey(this._nombreAtajo);
        if (this._dial) this._dial.cerrar();
        if (this._temporizador) {
            Mainloop.source_remove(this._temporizador);
            this._temporizador = 0;
        }
        this.settings.finalize();
    }

    _alCambiarRemoto() {
        const escuchaba = this._receptor.escuchando;
        this._receptorTs = 0;
        this._ultimoStatus = null;
        this._iconosLocales = {};
        this._firmaIconos = null;
        this._iconosReintento = 0;
        this._firmaMenu = null;
        if (escuchaba) {
            // el receptor sigue sonando con la configuración vieja (otro servidor, o ya no es modo remoto): se corta y,
            // si sigue en modo remoto, se vuelve a prender con la nueva
            this._receptor = Object.assign({}, this._receptor, { escuchando: false });
            this._correrReceptor(["off"], () => {
                if (!this.is_remote || !AppletDir.logic.parsearUrlServidor(this.server_url)) return this._sondear();
                this._correrReceptor(["on"], (r) => {
                    if (!r.error && r.codigo === 0) this._receptor = Object.assign({}, this._receptor, { escuchando: true });
                    this._sondear();
                });
            });
            return;
        }
        this._sondear();
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
        this._ponerBarras(AppletDir.barras.suena(estado));
        this._reconstruirMenu();
    }

    // Cambia el ícono por las barritas (o al revés) y arranca o frena la animación: solo corre mientras suena.
    _ponerBarras(suena) {
        const tam = this.getPanelIconSize(St.IconType.FULLCOLOR);
        const medidas = AppletDir.barras.medidas(tam, BARRAS_COLUMNAS, BARRAS_FILAS);
        this._medidasBarras = medidas;
        this._barras.set_size(Math.ceil(medidas.ancho), tam);
        this._applet_icon_box.visible = !suena;
        this._barras.visible = suena;
        if (suena && !this._animacionBarras) {
            this._animacionBarras = Mainloop.timeout_add(BARRAS_CUADRO_MS, () => {
                this._barras.queue_repaint();
                return true;
            });
        } else if (!suena && this._animacionBarras) {
            Mainloop.source_remove(this._animacionBarras);
            this._animacionBarras = 0;
        }
    }

    // Una grilla de puntos blancos: los de abajo de cada columna prendidos (según el instante) y el resto apenas visibles.
    _dibujarBarras(area) {
        const cr = area.get_context();
        const [ancho, alto] = area.get_surface_size();
        const m = this._medidasBarras;
        if (m) {
            const prendidos = AppletDir.barras.alturas(Date.now() - this._barrasT0, BARRAS_COLUMNAS, BARRAS_FILAS);
            const paso = m.punto + m.hueco;
            const x0 = (ancho - m.ancho) / 2;
            const base = (alto + m.alto) / 2;
            for (let c = 0; c < BARRAS_COLUMNAS; c++) {
                for (let f = 0; f < BARRAS_FILAS; f++) {
                    cr.setSourceRGBA(1, 1, 1, f < prendidos[c] ? 1 : 0.18);
                    cr.arc(x0 + c * paso + m.punto / 2, base - f * paso - m.punto / 2, m.punto / 2, 0, 2 * Math.PI);
                    cr.fill();
                }
            }
        }
        if (cr.$dispose) cr.$dispose();
    }

    _reconstruirMenu() {
        const estado = this.estado;
        const firma = estado ? JSON.stringify([estado.estaciones, estado.estacion, estado.encendida, this.is_remote]) : "";
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
        if (!this.is_remote) {      // en modo remoto no se edita nada: las emisoras son de la otra PC
            const nueva = new PopupMenu.PopupMenuItem("    Nueva emisora…");
            nueva.connect("activate", () => new DialogoEmisora(this).abrir());
            this._seccionEstaciones.addMenuItem(nueva);
        }
        if (estado.encendida) {
            // el único que corta la transmisión: el clic izquierdo, la pausa y el volumen en 0 solo silencian
            const apagar = new PopupMenu.PopupMenuItem("Apagar");
            apagar.connect("activate", () => this._accion("/apagar"));
            this._seccionEstaciones.addMenuItem(apagar);
        }
        this._seccionEstaciones.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    }

    // Al servicio local, o a la radio remota si `is_remote`.
    _pedir(metodo, ruta, cuerpo, callback) {
        if (this.is_remote) return this._pedirRemoto(metodo, ruta, cuerpo, callback);
        this._pedirHttp("127.0.0.1", this.puerto, null, metodo, ruta, cuerpo, callback);
    }

    // HTTP por un socket de GIO, todo asíncrono; cualquier error termina en callback({codigo: 0}).
    _pedirHttp(host, puerto, token, metodo, ruta, cuerpo, callback) {
        const cancelable = new Gio.Cancellable();
        let terminado = false;
        const terminar = (texto, vencio) => {
            if (terminado) return;
            terminado = true;
            if (!vencio) Mainloop.source_remove(vencimiento);
            try {
                callback(AppletDir.logic.parsearRespuesta(texto));
            } catch (e) {
                // si no, el catch de afuera se la traga sin rastro
                global.logError("cassette-fm: " + e + "\n" + e.stack);
            }
        };
        const vencimiento = Mainloop.timeout_add(TIMEOUT_MS, () => {
            cancelable.cancel();
            terminar(null, true);
            return false;
        });
        try {
            new Gio.SocketClient().connect_to_host_async(host + ":" + puerto, 0, cancelable,
                (cliente, resultado) => {
                    try {
                        const conexion = cliente.connect_to_host_finish(resultado);
                        const entrada = conexion.get_input_stream();
                        const salida = new Gio.DataOutputStream({ base_stream: conexion.get_output_stream() });
                        salida.put_string(AppletDir.logic.pedidoHttp(metodo, ruta, cuerpo, host, token), cancelable);
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

    // --- modo remoto ---

    _estadoRemoto(status, host) {
        return AppletDir.logic.estadoRemoto(status, this._receptor, host, this._iconosLocales);
    }

    // lan_receiver.py en esta PC (la escucha: prender, apagar, volumen); la dirección y la clave van por el entorno.
    _correrReceptor(argumentos, callback) {
        const entorno = { CASSETTE_LAN_URL: (this.server_url || "").trim(), CASSETTE_LAN_TOKEN: (this.server_token || "").trim() };
        return this._correr("python3", [this._dirApplet + "/lan_receiver.py", ...argumentos],
                            LIMITE_RECEPTOR_SEGUNDOS, callback, entorno);
    }

    // Al cambiar de emisora se vuelve a "en vivo": el receptor reconecta el stream y descarta lo acumulado (un retraso
    // por cortes de red no se recupera solo). Es cuando un salto no se nota; la espera se reinicia si llega otro cambio.
    _resincronizar() {
        if (this._resync) Mainloop.source_remove(this._resync);
        this._resync = 0;
        if (!this._receptor.escuchando) return;
        this._resync = Mainloop.timeout_add(RESYNC_ESPERA_MS, () => {
            this._resync = 0;
            if (!this._receptor.escuchando) return false;
            this._resincronizando = true;
            this._correrReceptor(["resync"], () => { this._resincronizando = false; });
            return false;
        });
    }

    // Para el cierre del dial: ¿ya suena la música de `estacion`? En modo remoto, cuando terminó de sincronizar (no hay
    // un resync esperando ni en curso); en local, cuando el servicio ya informa un tema nuevo de esa emisora.
    _musicaSonando(estacion, pistaAntes, callback) {
        if (this.is_remote) return callback(!this._resync && !this._resincronizando);
        this._pedir("GET", "/estado", undefined, (r) => {
            callback(r.codigo === 200 && AppletDir.logic.musicaSonando(r.datos, estacion, pistaAntes));
        });
    }

    // Baja los logos con el receptor solo cuando cambia la lista que publica la radio (y, si falla, no antes de 30 s).
    _actualizarIconos(publicados) {
        const firma = JSON.stringify(publicados);
        if (firma === this._firmaIconos || Date.now() < this._iconosReintento) return;
        this._firmaIconos = firma;
        if (firma === "{}") {
            this._iconosLocales = {};
            return;
        }
        this._correrReceptor(["icons"], (r) => {
            const locales = r.error || r.codigo !== 0 ? null : AppletDir.logic.parsearIconos(r.stdout);
            if (locales === null) {
                this._firmaIconos = null;
                this._iconosReintento = Date.now() + ICONOS_REINTENTO_MS;
                return;
            }
            this._iconosLocales = locales;
            if (this._ultimoStatus) this._aplicar(this._estadoRemoto(this._ultimoStatus, this._hostRemoto()));
        });
    }

    _hostRemoto() {
        const servidor = AppletDir.logic.parsearUrlServidor(this.server_url);
        return servidor ? servidor.host : (this.server_url || "");
    }

    // Se entera de cómo está la escucha local (¿murió mpv?, ¿se cortó el stream?) cada tanto, no en cada sondeo.
    _receptorAlDia(callback) {
        if (Date.now() - this._receptorTs < RECEPTOR_AL_DIA_MS) return callback();
        this._correrReceptor(["status", "--json"], (r) => {
            const estado = r.error ? null : AppletDir.logic.parsearReceptor(r.stdout);
            if (estado) this._receptor = estado;
            this._receptorTs = Date.now();
            callback();
        });
    }

    // Traduce un pedido al servicio local a la radio remota (logic.planRemoto): la emisora y el estado son de la API de
    // la PC principal; el encendido y el volumen, del receptor de esta PC. Siempre responde 200 con un estado.
    _pedirRemoto(metodo, ruta, cuerpo, callback) {
        const servidor = AppletDir.logic.parsearUrlServidor(this.server_url);
        const host = servidor ? servidor.host : (this.server_url || "");
        const responder = (status) => {
            this._ultimoStatus = status;
            if (status.codigo === 200 && status.datos) this._actualizarIconos(status.datos.iconos || {});
            callback({ codigo: 200, datos: this._estadoRemoto(status, host) });
        };
        const ultimo = () => this._ultimoStatus || { codigo: 0, datos: null };
        if (!servidor) {
            const estado = this._estadoRemoto({ codigo: 0, datos: null }, host);
            estado.aviso = "falta la dirección de la radio (ajustes del applet)";
            return callback({ codigo: 200, datos: estado });
        }
        const estadoActual = this._ultimoStatus && this._ultimoStatus.datos ? this._ultimoStatus.datos : null;
        const plan = AppletDir.logic.planRemoto(ruta, cuerpo, estadoActual, this._receptor);
        if (plan.destino === "servidor") {
            const pedir = (m, r, despues) => this._pedirHttp(servidor.host, servidor.puerto, this.server_token, m, r,
                                                             undefined, despues);
            if (plan.ruta === "/status") {
                this._receptorAlDia(() => pedir("GET", "/status", responder));
            } else {
                pedir(plan.metodo, plan.ruta, (r) => {
                    // 404: la lista cambió en la otra PC; se vuelve a pedir el estado y el menú se refresca
                    if (r.codigo === 404) pedir("GET", "/status", responder);
                    else {
                        if (r.codigo === 200) this._resincronizar();
                        responder(r);
                    }
                });
            }
        } else if (plan.destino === "receptor") {
            this._correrReceptor(plan.argumentos, (r) => {
                if (r.error || r.codigo !== 0) {
                    return callback({ codigo: 500, datos: { error: r.error || (r.stderr || "").trim() || "lan_receiver.py falló" } });
                }
                if (plan.argumentos[0] === "on") this._receptor = Object.assign({}, this._receptor, { escuchando: true, error: null });
                else if (plan.argumentos[0] === "off") this._receptor = Object.assign({}, this._receptor, { escuchando: false });
                else if (plan.argumentos[0] === "volume") this._receptor = Object.assign({}, this._receptor, { volumen: parseInt(r.stdout, 10) });
                this._receptorTs = Date.now();
                responder(ultimo());
            });
        } else {
            responder(ultimo());
        }
    }

    // Corre `<programa> <argumentos>` sin shell y sin bloquear el panel; callback({codigo, stdout, stderr}) o
    // callback({error}) si no se encuentra, no arranca o pasa el límite (y entonces se lo corta). Devuelve el
    // proceso (para cortarlo con force_exit) o null si no arrancó.
    _correr(programa, argumentos, segundos, callback, entorno) {
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
            const banderas = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE;
            if (entorno) {          // variables extra (la clave del modo remoto): no van por argumentos
                const lanzador = new Gio.SubprocessLauncher({ flags: banderas });
                for (const nombre of Object.keys(entorno)) lanzador.setenv(nombre, entorno[nombre], true);
                proceso = lanzador.spawnv([ruta, ...argumentos]);
            } else {
                proceso = Gio.Subprocess.new([ruta, ...argumentos], banderas);
            }
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

        this._icono = null;             // la imagen elegida para el logo (null: el genérico)
        this._miniatura = new St.Icon({ icon_size: 48 });
        this._botonExaminar = new St.Button({ label: "Examinar…", style_class: "dialog-button", can_focus: true });
        this._botonExaminar.connect("clicked", () => this._alExaminar());
        this._botonQuitarLogo = new St.Button({ label: "Quitar", style_class: "dialog-button", can_focus: true });
        this._botonQuitarLogo.connect("clicked", () => {
            this._icono = null;
            this._refrescar();
        });
        caja.add_child(fila("Logo", this._miniatura, this._botonExaminar, this._botonQuitarLogo));

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
        const antes = this._seleccion.voz;
        this._seleccion = AppletDir.logic.elegirIdioma(this._seleccion, idioma);
        if (this._seleccion.voz !== antes) this._cortarMuestra();     // la voz volvió a "Al azar"
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
        this._miniatura.gicon = Gio.FileIcon.new(Gio.File.new_for_path(this._icono || this._applet.generico));
        this._botonQuitarLogo.reactive = this._icono !== null;
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

    // "Examinar…": zenity elige la imagen. Mientras está abierto, el modal suelta el teclado y el mouse y se esconde
    // (si no, la ventana de zenity queda tapada e inalcanzable); al cerrarse, vuelve.
    _alExaminar() {
        this._cortarMuestra();
        this._dialogo.popModal();
        this._dialogo.hide();
        this._applet._correr("zenity", AppletDir.logic.argumentosExaminar(), LIMITE_EXAMINAR_SEGUNDOS, (r) => {
            if (this._cerrado) return;
            this._dialogo.show();
            this._dialogo.pushModal();
            const ruta = r.error ? null : AppletDir.logic.rutaElegida(r.codigo, r.stdout);
            if (ruta) this._icono = ruta;
            else if (r.error) this._mostrarError("No pude abrir el selector de imágenes: " + r.error);
            this._refrescar();
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
        for (const boton of [this._botonVoz, this._botonMuestra, this._botonExaminar, this._botonQuitarLogo,
                             ...this._botonesIdioma, ...this._opciones.get_children()])
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
        const argumentos = AppletDir.logic.argumentosNueva(nombre, link, this._seleccion, this._icono);
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

// --- El dial: la tira de logos estilo GTA 4 (Super+Alt+Espacio) ---

const DIAL_GRANDE = 160;            // el logo de la emisora actual
const DIAL_CHICO = 96;              // los demás
const DIAL_PASO = 120;              // distancia entre los centros de los logos chicos
const DIAL_LADO = 3;                // logos a cada lado de la actual
const DIAL_ANIMACION_MS = 150;
const DIAL_CIERRE_MS = 3000;        // sin tocar nada, se cierra solo (cuenta desde que suena la música de la emisora)
const DIAL_ESPERA_MAX_MS = 12000;   // mientras sintoniza: lo más que espera la música antes de cerrarse igual
const DIAL_VIGILIA_MS = 300;        // cada cuánto mira si ya suena
const DIAL_AVISO_MS = 2000;         // lo que dura el aviso de "no responde"
const DIAL_PASO_VOLUMEN = 5;
const DIAL_ESCALA = 1;           // tamaño de todo el dial (logos, textos y recuadro); 1 = el diseño original
const DIAL_ALTURA = 0.08;           // el borde de arriba de la tira, en fracción del alto del monitor
const DIAL_ANCHO_TEXTOS = 350;      // ancho fijo del recuadro de los textos (centrado bajo la fila)

// El Clutter de Cinnamon no sabe dar el nombre de una tecla: los que entiende teclaDial, a mano.
function _nombreDeTecla(simbolo) {
    const nombres = { [Clutter.KEY_Left]: "Left", [Clutter.KEY_Right]: "Right", [Clutter.KEY_Up]: "Up",
                      [Clutter.KEY_Down]: "Down", [Clutter.KEY_Escape]: "Escape", [Clutter.KEY_Return]: "Return",
                      [Clutter.KEY_KP_Enter]: "Return",
                      // teclado numérico: sin NumLock manda KP_Left/…; con NumLock, los dígitos 4/6/8/2
                      [Clutter.KEY_KP_Left]: "Left", [Clutter.KEY_KP_Right]: "Right", [Clutter.KEY_KP_Up]: "Up",
                      [Clutter.KEY_KP_Down]: "Down", [Clutter.KEY_KP_4]: "Left", [Clutter.KEY_KP_6]: "Right",
                      [Clutter.KEY_KP_8]: "Up", [Clutter.KEY_KP_2]: "Down" };
    return nombres[simbolo] || null;
}

// Centro (en x, relativo al centro de la fila) del logo con desplazamiento `d`.
function _centroDial(d) {
    if (d === 0) return 0;
    const primero = DIAL_GRANDE / 2 + DIAL_CHICO / 2 + 16;
    return Math.sign(d) * (primero + (Math.abs(d) - 1) * DIAL_PASO);
}

// La fila se desvanece hacia los dos costados (un degradado del alfa, de 0 en los bordes a entero en el centro).
function _difuminado() {
    const efecto = new Clutter.ShaderEffect({ shader_type: Clutter.ShaderType.FRAGMENT_SHADER });
    efecto.set_shader_source("uniform sampler2D tex;"
        + " void main() {"
        + "   vec4 c = texture2D(tex, cogl_tex_coord_in[0].st);"
        + "   float x = cogl_tex_coord_in[0].s;"
        + "   cogl_color_out = c * smoothstep(0.0, 0.38, x) * smoothstep(1.0, 0.62, x);"
        + " }");
    efecto.set_uniform_value("tex", 0);
    return efecto;
}

// Compone actores de St sobre Main.uiGroup: un fondo transparente que ocupa la pantalla (toma el teclado y cierra
// con un clic afuera) y la tira centrada a un tercio de alto del monitor principal.
class Dial {
    constructor(applet) {
        this._applet = applet;
        this._cerrado = false;
        this._estado = null;
        this._actual = null;
        this._volumen = 0;
        this._logos = new Map();        // nombre → St.Icon
        this._lugares = new Map();      // nombre → desplazamiento visible (undefined: no se ve)
        this._vencimiento = 0;
        this._sintonizando = false;     // se pidió una emisora y todavía no suena
        this._temaAntes = null;
        this._vigilia = 0;
        this._vigiliaTimer = 0;
        this._colaEmisora = AppletDir.logic.crearCola((nombre) =>
            applet._pedir("POST", "/sintonizar", { estacion: nombre }, (r) => this._alResponder(r, this._colaEmisora, true)));
        this._colaVolumen = AppletDir.logic.crearCola((valor) =>
            applet._pedir("POST", "/volumen", { valor: valor }, (r) => this._alResponder(r, this._colaVolumen, false)));

        const monitor = Main.layoutManager.primaryMonitor;
        this._fondo = new St.Widget({ reactive: true, x: monitor.x, y: monitor.y,
                                      width: monitor.width, height: monitor.height });
        // sin caja: los logos flotan y solo los textos llevan un recuadro semitransparente
        this._tira = new St.BoxLayout({ vertical: true, reactive: true, style: "spacing: 10px;" });
        this._fila = new St.Widget({ width: 2 * (_centroDial(DIAL_LADO) + DIAL_CHICO / 2), height: DIAL_GRANDE,
                                     clip_to_allocation: true });
        this._fila.add_effect(_difuminado());
        this._textos = new St.BoxLayout({ vertical: true, width: DIAL_ANCHO_TEXTOS, x_expand: true,
                                          x_align: Clutter.ActorAlign.CENTER,
                                          style: "background-color: rgba(20, 20, 26, 0.6); border-radius: 18px;"
                                                 + " padding: 10px 24px; spacing: 4px;" });
        // a lo ancho de la tira y centrados: si no, se quedan con la medida del primer texto ("…")
        this._nombre = new St.Label({ style: "font-size: 1.5em; font-weight: bold; color: #fff; text-align: center;",
                                      x_expand: true });
        this._ayuda = new St.Label({ style: "font-size: 1.25em; color: rgba(255,255,255,0.8); text-align: center;",
                                     x_expand: true });
        for (const hijo of [this._nombre, this._ayuda]) this._textos.add_child(hijo);
        this._tira.add_child(this._fila);
        this._tira.add_child(this._textos);
        this._tira.set_pivot_point(0.5, 0);       // achica hacia el centro, sin mover el borde de arriba
        this._tira.set_scale(DIAL_ESCALA, DIAL_ESCALA);
        this._fondo.add_child(this._tira);
        this._fondo.opacity = 0;
        Main.uiGroup.add_child(this._fondo);

        this._fondo.connect("key-press-event", (actor, event) => this._alTecla(event));
        this._fondo.connect("button-press-event", (actor, event) => {
            if (event.get_source() === this._fondo) this.cerrar();
            return Clutter.EVENT_STOP;
        });
        this._tira.connect("scroll-event", (actor, event) => {
            const direccion = event.get_scroll_direction();
            if (direccion === Clutter.ScrollDirection.UP) this._mover(-1);
            else if (direccion === Clutter.ScrollDirection.DOWN) this._mover(+1);
            return Clutter.EVENT_STOP;
        });
        this._modal = Main.pushModal(this._fondo);
        this._fondo.grab_key_focus();
        this._mostrarAviso("…");
        this._fondo.ease({ opacity: 255, duration: DIAL_ANIMACION_MS, mode: Clutter.AnimationMode.EASE_OUT_QUAD });
        this._reiniciarCierre();        // antes de pedir nada: pase lo que pase, se cierra solo

        applet._pedir("GET", "/estado", undefined, (r) => {
            if (this._cerrado) return;
            if (r.codigo !== 200) return this._avisarYCerrar("cassette-fm no responde");
            // con el bus de audio la radio puede estar prendida pero silenciada (monitor_local: false)
            if (r.datos.encendida && r.datos.monitor_local !== false) return this._empezar(r.datos);
            // abrir el dial prende la radio (con el volumen en 0, la API la sube a 50)
            applet._pedir("POST", "/encender", undefined, (e) => {
                if (this._cerrado) return;
                if (e.codigo !== 200)
                    return this._avisarYCerrar(e.datos && e.datos.error ? e.datos.error : "cassette-fm no responde");
                applet._aplicar(e.datos);
                this._empezar(e.datos);
                // se prendió la radio: el cierre cuenta desde que suena la música
                this._temaAntes = null;
                this._sintonizando = true;
                this._reiniciarCierre();
                this._vigilarMusica(++this._vigilia);
            });
        });
    }

    _empezar(estado) {
        this._estado = estado;
        this._actual = estado.estacion;
        this._volumen = estado.volumen;
        for (const nombre of estado.estaciones) {
            const ruta = AppletDir.logic.iconoDe(nombre, estado.iconos, this._applet.generico);
            const logo = new St.Icon({ gicon: Gio.FileIcon.new(Gio.File.new_for_path(ruta)),
                                       icon_size: DIAL_GRANDE, reactive: true, opacity: 0 });
            logo.set_pivot_point(0.5, 0.5);
            logo.connect("button-press-event", () => {
                this._elegir(nombre);
                return Clutter.EVENT_STOP;
            });
            this._fila.add_child(logo);
            this._logos.set(nombre, logo);
        }
        this._ubicar(false);
        this._refrescarTextos();
        this._reiniciarCierre();
    }

    // Lleva cada logo a su lugar según la emisora actual; los que dan la vuelta (de un extremo al otro) aparecen sin
    // cruzar la fila.
    _ubicar(animado) {
        const fila = AppletDir.logic.filaDial(this._estado.estaciones, this._actual, DIAL_LADO);
        const nuevos = new Map(fila.map((e) => [e.nombre, e.desplazamiento]));
        const mitad = this._fila.width / 2;
        for (const [nombre, logo] of this._logos) {
            const antes = this._lugares.get(nombre);
            const d = nuevos.get(nombre);
            const visible = d !== undefined;
            const destino = {
                x: mitad + _centroDial(visible ? d : 0) - DIAL_GRANDE / 2,
                scale_x: d === 0 ? 1 : DIAL_CHICO / DIAL_GRANDE,
                scale_y: d === 0 ? 1 : DIAL_CHICO / DIAL_GRANDE,
                opacity: !visible ? 0 : d === 0 ? 255 : 210,
            };
            const salta = antes === undefined || !visible || Math.abs(antes - d) > 1;
            logo.remove_all_transitions();
            if (!animado || salta) {
                logo.set_position(destino.x, 0);
                logo.set_scale(destino.scale_x, destino.scale_y);
                if (animado && visible) {
                    logo.opacity = 0;
                    logo.ease({ opacity: destino.opacity, duration: DIAL_ANIMACION_MS,
                                mode: Clutter.AnimationMode.EASE_OUT_QUAD });
                } else {
                    logo.opacity = destino.opacity;
                }
            } else {
                logo.ease(Object.assign({ duration: DIAL_ANIMACION_MS, mode: Clutter.AnimationMode.EASE_OUT_QUAD },
                                        destino));
            }
            logo.reactive = visible;
        }
        this._lugares = nuevos;
    }

    _refrescarTextos() {
        this._nombre.text = this._actual || "";
        this._ayuda.text = AppletDir.logic.barraVolumen(this._volumen);
        this._centrar();
    }

    _centrar() {
        this._tira.queue_relayout();
        const monitor = Main.layoutManager.primaryMonitor;
        const [, ancho] = this._tira.get_preferred_width(-1);
        const [, alto] = this._tira.get_preferred_height(ancho);
        this._tira.set_position(Math.round((monitor.width - ancho) / 2), Math.round(monitor.height * DIAL_ALTURA));
    }

    _mostrarAviso(texto) {
        this._nombre.text = texto;
        this._ayuda.text = " ";
        this._centrar();
    }

    _avisarYCerrar(texto) {
        this._mostrarAviso(texto);
        this._reiniciarCierre(DIAL_AVISO_MS);
    }

    _reiniciarCierre(ms) {
        // sintonizando, el cierre espera a que suene la música (ver _vigilarMusica); si no, 3 s sin tocar nada
        if (ms === undefined) ms = this._sintonizando ? DIAL_ESPERA_MAX_MS : DIAL_CIERRE_MS;
        if (this._vencimiento) Mainloop.source_remove(this._vencimiento);
        this._vencimiento = Mainloop.timeout_add(ms, () => {
            this._vencimiento = 0;
            this.cerrar();
            return false;
        });
    }

    _alTecla(event) {
        const accion = AppletDir.logic.teclaDial(_nombreDeTecla(event.get_key_symbol()));
        if (accion === "cerrar") this.cerrar();
        else if (accion === "anterior") this._mover(-1);
        else if (accion === "siguiente") this._mover(+1);
        else if (accion === "subir") this._cambiarVolumen(+DIAL_PASO_VOLUMEN);
        else if (accion === "bajar") this._cambiarVolumen(-DIAL_PASO_VOLUMEN);
        return Clutter.EVENT_STOP;
    }

    _mover(paso) {
        if (!this._estado || this._estado.estaciones.length === 0) return;
        const lista = this._estado.estaciones;
        const i = Math.max(0, lista.indexOf(this._actual));
        this._elegir(lista[((i + paso) % lista.length + lista.length) % lista.length]);
    }

    // La tira se mueve en el acto; a la radio le llega de a un pedido (con la radio apagada, sintonizar la prende).
    _elegir(nombre) {
        if (!this._estado) return;
        this._reiniciarCierre();
        if (nombre === this._actual && this._estado.encendida) return;
        this._actual = nombre;
        this._temaAntes = this._estado.pista || null;
        this._sintonizando = true;      // el cierre de 3 s cuenta desde que suena la música, no desde que se pide
        this._reiniciarCierre();
        this._ubicar(true);
        this._refrescarTextos();
        this._colaEmisora.pedir(nombre);
    }

    _cambiarVolumen(delta) {
        if (!this._estado) return;
        this._reiniciarCierre();
        const nuevo = Math.max(0, Math.min(100, this._volumen + delta));
        if (nuevo === this._volumen) return;
        this._volumen = nuevo;          // en 0 la API apaga la radio; subir desde 0 la prende
        this._refrescarTextos();
        this._colaVolumen.pedir(nuevo);
    }

    _alResponder(r, cola, eraSintonizar) {
        cola.listo();
        if (this._cerrado || r.codigo !== 200) return;
        this._applet._aplicar(r.datos);
        this._estado = Object.assign({}, this._estado, r.datos, { iconos: this._estado.iconos });
        this._volumen = AppletDir.logic.volumenTrasRespuesta(this._volumen, r.datos.volumen, eraSintonizar);
        this._refrescarTextos();
        if (eraSintonizar) this._vigilarMusica(++this._vigilia);
    }

    // Mira cada tanto si ya suena la música de la emisora elegida; entonces sí empiezan los 3 s del cierre. Cada nueva
    // elección (o el cierre del dial) cancela la vigilia anterior.
    _vigilarMusica(vigilia) {
        if (this._vigiliaTimer) Mainloop.source_remove(this._vigiliaTimer);
        this._vigiliaTimer = 0;
        if (this._cerrado || vigilia !== this._vigilia) return;
        this._applet._musicaSonando(this._actual, this._temaAntes, (suena) => {
            if (this._cerrado || vigilia !== this._vigilia) return;
            if (suena) {
                this._sintonizando = false;
                this._reiniciarCierre();
            } else {
                this._vigiliaTimer = Mainloop.timeout_add(DIAL_VIGILIA_MS, () => {
                    this._vigiliaTimer = 0;
                    this._vigilarMusica(vigilia);
                    return false;
                });
            }
        });
    }

    cerrar() {
        if (this._cerrado) return;
        this._cerrado = true;
        if (this._vencimiento) Mainloop.source_remove(this._vencimiento);
        this._vencimiento = 0;
        if (this._vigiliaTimer) Mainloop.source_remove(this._vigiliaTimer);
        this._vigiliaTimer = 0;
        if (this._modal) Main.popModal(this._fondo);
        this._modal = false;
        if (this._applet._dial === this) this._applet._dial = null;
        this._fondo.ease({ opacity: 0, duration: DIAL_ANIMACION_MS, mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                           onComplete: () => this._fondo.destroy() });
    }
}

function main(metadata, orientation, panelHeight, instanceId) {
    AppletDir = imports.ui.appletManager.applets[UUID];
    return new CassetteApplet(metadata, orientation, panelHeight, instanceId);
}
