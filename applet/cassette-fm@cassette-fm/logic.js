// Lógica pura del applet de cassette-fm: sin dependencias de Cinnamon, así se prueba con Node.
// En Cinnamon se usa como `AppletDir.logic.<función>`; en Node, con require().

function etiqueta(estado, mostrarEstacion) {
    if (!estado || !estado.encendida || !mostrarEstacion) return "";
    return estado.estacion || "";
}

function tooltip(estado) {
    if (!estado) return "cassette-fm no responde";
    let lineas;
    if (!estado.encendida) {
        lineas = ["Apagada · volumen " + estado.volumen];
    } else {
        lineas = [estado.estacion];
        if (estado.pista) lineas.push(estado.pista);
        lineas.push("Volumen " + estado.volumen);
    }
    if (estado.aviso) lineas.push(estado.aviso);     // modo remoto: por qué no hay radio o no se oye
    return lineas.join("\n");
}

function accionDeRueda(direccion) {
    if (direccion === "up") return "siguiente";
    if (direccion === "down") return "anterior";
    return null;
}

// Devuelve ahoraMs => bool: true si pasaron esperaMs desde la última vez que devolvió true.
function crearLimitador(esperaMs) {
    let ultimo = -Infinity;
    return function (ahoraMs) {
        if (ahoraMs - ultimo < esperaMs) return false;
        ultimo = ahoraMs;
        return true;
    };
}

function _bytesUtf8(texto) {
    return unescape(encodeURIComponent(texto)).length;
}

function pedidoHttp(metodo, ruta, cuerpo, host, token) {
    let cabeceras = metodo + " " + ruta + " HTTP/1.0\r\nHost: " + (host || "127.0.0.1") + "\r\n";
    if (token) cabeceras += "Authorization: Bearer " + token + "\r\n";
    let json = "";
    if (cuerpo !== undefined) {
        json = JSON.stringify(cuerpo);
        cabeceras += "Content-Type: application/json\r\nContent-Length: " + _bytesUtf8(json) + "\r\n";
    }
    return cabeceras + "\r\n" + json;
}

// {codigo, datos}; cualquier cosa que no sea una respuesta HTTP con cuerpo JSON válido => {0, null}.
function parsearRespuesta(texto) {
    const caido = { codigo: 0, datos: null };
    if (typeof texto !== "string") return caido;
    const corte = texto.indexOf("\r\n\r\n");
    if (corte < 0) return caido;
    const estado = /^HTTP\/\d\.\d (\d{3})/.exec(texto);
    if (!estado) return caido;
    try {
        return { codigo: parseInt(estado[1], 10), datos: JSON.parse(texto.slice(corte + 4)) };
    } catch (e) {
        return caido;
    }
}

// --- Modal de emisora nueva: corre `cassette voces --json` y `cassette nueva …` ---

// La salida de `cassette voces --json`: [{alias, voz, idioma, emisoras}]; cualquier otra cosa => null.
function parsearVoces(texto) {
    if (typeof texto !== "string") return null;
    let voces;
    try {
        voces = JSON.parse(texto);
    } catch (e) {
        return null;
    }
    if (!Array.isArray(voces)) return null;
    const valida = (v) => v !== null && typeof v === "object" && typeof v.alias === "string"
        && typeof v.idioma === "string" && Array.isArray(v.emisoras);
    return voces.every(valida) ? voces : null;
}

// "es" o "en" ("en-gb" habla inglés); "" si no es ninguno.
function idiomaBase(idioma) {
    const base = typeof idioma === "string" ? idioma.split("-")[0] : "";
    return base === "es" || base === "en" ? base : "";
}

function vocesDelIdioma(voces, idioma) {
    if (idioma === "") return voces;
    return voces.filter((v) => idiomaBase(v.idioma) === idioma);
}

function etiquetaDeVoz(voz) {
    if (!voz) return "Al azar";
    return voz.emisoras.length ? voz.alias + " · " + voz.emisoras.join(", ") : voz.alias;
}

// La selección del modal es {idioma: "" | "es" | "en", voz: una de las voces o null (al azar)}.
function elegirVoz(seleccion, voz) {
    const idioma = seleccion.idioma === "" && voz ? idiomaBase(voz.idioma) : seleccion.idioma;
    return { idioma: idioma, voz: voz };
}

function elegirIdioma(seleccion, idioma) {
    const habla = !seleccion.voz || idioma === "" || idiomaBase(seleccion.voz.idioma) === idioma;
    return { idioma: idioma, voz: habla ? seleccion.voz : null };
}

function faltante(nombre, link) {
    if (!nombre.trim()) return "Falta el nombre";
    if (!link.trim()) return "Falta el link de la playlist";
    return null;
}

// Los argumentos de `cassette nueva`, uno por elemento: el proceso se lanza sin shell. Las opciones van antes de
// "--" para que un nombre que empieza con "-" no se tome como opción.
function argumentosNueva(nombre, link, seleccion, icono) {
    const args = ["nueva"];
    if (seleccion.voz) args.push("--voz", seleccion.voz.alias);
    if (seleccion.idioma !== "") args.push("--idioma", seleccion.idioma);
    if (icono) args.push("--icono=" + icono);
    return args.concat(["--", nombre, link]);
}

// "Examinar…" del logo: zenity elige la imagen (el filtro distingue mayúsculas).
function argumentosExaminar() {
    return ["--file-selection", "--title=Logo de la emisora",
            "--file-filter=Imágenes | *.png *.jpg *.jpeg *.svg *.PNG *.JPG *.JPEG *.SVG"];
}

// La ruta que eligió zenity, o null si se canceló (sale con 1) o no dijo nada.
function rutaElegida(codigo, stdout) {
    if (codigo !== 0) return null;
    const ruta = (stdout || "").replace(/\n+$/, "");
    return ruta.trim() ? ruta : null;
}

function mensajeDeError(codigo, stdout, stderr) {
    const error = (stderr || "").trim();
    if (error) return error;
    const lineas = (stdout || "").split("\n").map((l) => l.trim()).filter((l) => l);
    if (lineas.length) return lineas[lineas.length - 1];
    return "cassette nueva terminó con error (código " + codigo + ")";
}

// --- Muestra de voz: ▶ al lado de la voz corre `cassette-dj muestra` y reproduce el WAV ---

// Cada valor pegado a su opción (--radio=-h): un nombre que empieza con "-" no se toma como otra opción.
function argumentosMuestra(voz, nombre) {
    return ["muestra", "--voz=" + voz.alias, "--idioma=" + voz.idioma, "--radio=" + nombre.trim()];
}

// fase: "quieto" | "generando" | "sonando"; sin voz elegida (al azar) no hay muestra.
function botonMuestra(voz, fase) {
    if (!voz) return { texto: "▶", activo: false };
    if (fase === "generando") return { texto: "…", activo: false };
    if (fase === "sonando") return { texto: "■", activo: true };
    return { texto: "▶", activo: true };
}

function rutaDeMuestra(stdout) {
    const lineas = (stdout || "").split("\n").map((l) => l.trim()).filter((l) => l);
    const ultima = lineas.length ? lineas[lineas.length - 1] : "";
    return ultima.endsWith(".wav") ? ultima : null;
}

// --- El dial: la tira de logos que se abre con su atajo ---

// Los logos que se ven, de izquierda a derecha: {nombre, desplazamiento} con la actual en 0. La fila es circular
// (como ◀ ▶); con más de 2*lado+1 emisoras se ven `lado` a cada lado; con menos, todas (la que sobra, a la derecha).
function filaDial(estaciones, actual, lado = 3) {
    const n = estaciones.length;
    if (n === 0) return [];
    const i = Math.max(0, estaciones.indexOf(actual));
    const izquierda = n > 2 * lado + 1 ? lado : Math.floor((n - 1) / 2);
    const derecha = n > 2 * lado + 1 ? lado : n - 1 - izquierda;
    const fila = [];
    for (let d = -izquierda; d <= derecha; d++)
        fila.push({ nombre: estaciones[((i + d) % n + n) % n], desplazamiento: d });
    return fila;
}

const _TECLAS_DIAL = { Left: "anterior", Right: "siguiente", Up: "subir", Down: "bajar", Escape: "cerrar",
                      Return: "cerrar" };

function teclaDial(nombreTecla) {
    return _TECLAS_DIAL[nombreTecla] || null;
}

// Pedidos a la radio de a uno: si llega otro mientras uno está en curso, al terminar se manda solo el último
// (cinco ▶ seguidos no encolan cinco cambios). `listo()` se llama cuando vuelve la respuesta.
function crearCola(enviar) {
    let enCurso = false;
    let pendiente;
    let hayPendiente = false;
    return {
        pedir(destino) {
            if (enCurso) {
                pendiente = destino;
                hayPendiente = true;
                return;
            }
            enCurso = true;
            enviar(destino);
        },
        listo() {
            enCurso = false;
            if (!hayPendiente) return;
            hayPendiente = false;
            this.pedir(pendiente);
        },
    };
}

function barraVolumen(v) {
    if (v === 0) return "Apagada";
    const llenas = Math.round(v / 5);          // un cuadrado por cada 5 %
    return "▮".repeat(llenas) + "▱".repeat(20 - llenas) + " " + v;
}

// --- modo remoto: la radio está en otra PC (lan_server.py) y acá solo se escucha ---

const PUERTO_REMOTO = 8765;

// "http://100.104.222.41:8765" => {host, puerto}; solo http, y null con cualquier otra cosa.
function parsearUrlServidor(url) {
    if (typeof url !== "string") return null;
    const m = /^http:\/\/([^\/:\s]+)(?::(\d{1,5}))?\/?$/.exec(url.trim());
    if (!m) return null;
    const puerto = m[2] === undefined ? PUERTO_REMOTO : parseInt(m[2], 10);
    return puerto >= 1 && puerto <= 65535 ? { host: m[1], puerto: puerto } : null;
}

function idEstacion(nombre) {
    return encodeURIComponent(nombre);
}

function _acotar(n) {
    return Math.max(0, Math.min(100, Math.round(n)));
}

// Qué hacer con un pedido que el applet haría a su servicio local, cuando la radio es remota:
// {destino: "servidor", metodo, ruta} (la API de la PC principal), {destino: "receptor", argumentos} (lan_receiver.py
// en esta PC) o {destino: "ninguno"}. El encendido y el volumen son de esta PC; la emisora es de la principal.
function planRemoto(ruta, cuerpo, estado, receptor) {
    receptor = receptor || { escuchando: false, volumen: 70 };
    const emisoras = estado && Array.isArray(estado.estaciones) ? estado.estaciones : [];
    const hacia = (paso) => {
        if (emisoras.length === 0) return { destino: "ninguno" };
        const actual = emisoras.indexOf(estado.estacion);
        const destino = actual < 0 ? (paso > 0 ? 0 : emisoras.length - 1)
                                   : (actual + paso + emisoras.length) % emisoras.length;
        return { destino: "servidor", metodo: "POST", ruta: "/station/" + idEstacion(emisoras[destino]) };
    };
    switch (ruta) {
    case "/estado":
        return { destino: "servidor", metodo: "GET", ruta: "/status" };
    case "/sintonizar":
        if (!cuerpo || typeof cuerpo.estacion !== "string") return { destino: "ninguno" };
        return { destino: "servidor", metodo: "POST", ruta: "/station/" + idEstacion(cuerpo.estacion) };
    case "/siguiente":
        return hacia(+1);
    case "/anterior":
        return hacia(-1);
    case "/alternar":
        return { destino: "receptor", argumentos: [receptor.escuchando ? "off" : "on"] };
    case "/encender":
        return { destino: "receptor", argumentos: ["on"] };
    case "/apagar":
        return { destino: "receptor", argumentos: ["off"] };
    case "/volumen": {
        if (!cuerpo) return { destino: "ninguno" };
        let nuevo;
        if (typeof cuerpo.valor === "number") nuevo = cuerpo.valor;
        else if (typeof cuerpo.delta === "number") nuevo = receptor.volumen + cuerpo.delta;
        else return { destino: "ninguno" };
        return { destino: "receptor", argumentos: ["volume", String(_acotar(nuevo))] };
    }
    default:
        return { destino: "ninguno" };
    }
}

// El estado que el applet muestra en modo remoto: lo de la radio sale del servidor ({codigo, datos} de /status), el
// encendido y el volumen del receptor local ({escuchando, volumen, error}); `aviso` dice por qué algo no anda.
function estadoRemoto(status, receptor, host, iconosLocales) {
    const base = { encendida: !!receptor.escuchando, volumen: receptor.volumen, estacion: null, pista: null,
                   estaciones: [], fuente: null, segundo: null, iconos: {} };
    if (!status || status.codigo === 0 || !status.datos) {
        return Object.assign(base, { aviso: "no alcanzo a la radio en " + host });
    }
    if (status.codigo === 401 || status.codigo === 403) return Object.assign(base, { aviso: "clave rechazada" });
    if (status.codigo !== 200) return Object.assign(base, { aviso: "la radio en " + host + " respondió " + status.codigo });
    const d = status.datos;
    const estado = Object.assign(base, { estacion: d.estacion, pista: d.pista, estaciones: d.estaciones || [],
                                         fuente: d.fuente, segundo: d.segundo, iconos: {} });
    // los logos ya bajados a esta PC (lan_receiver.py icons), solo los que el servidor sigue publicando
    for (const nombre of Object.keys(d.iconos || {})) {
        if (iconosLocales && iconosLocales[nombre]) estado.iconos[nombre] = iconosLocales[nombre];
    }
    if (receptor.error) estado.aviso = "audio: " + receptor.error;
    else if (!d.encendida && receptor.escuchando) estado.aviso = "la radio principal está apagada";
    return estado;
}

// La salida de `lan_receiver.py icons` => {emisora: ruta local}, o null si no se entiende.
function parsearIconos(texto) {
    if (typeof texto !== "string") return null;
    try {
        const d = JSON.parse(texto);
        if (!d || typeof d !== "object" || Array.isArray(d)) return null;
        for (const nombre of Object.keys(d)) if (typeof d[nombre] !== "string") return null;
        return d;
    } catch (e) {
        return null;
    }
}

// La salida de `lan_receiver.py status --json` => {escuchando, volumen, error}, o null si no se entiende.
function parsearReceptor(texto) {
    if (typeof texto !== "string") return null;
    try {
        const d = JSON.parse(texto);
        if (!d || typeof d.escuchando !== "boolean" || typeof d.volumen !== "number") return null;
        return { escuchando: d.escuchando, volumen: d.volumen, error: typeof d.error === "string" ? d.error : null };
    } catch (e) {
        return null;
    }
}

// ¿Ya suena música de la emisora pedida? (el cierre del dial cuenta desde ahí). `pistaAntes` es el tema que había al
// pedirla: mientras siga ese, todavía no cambió (null: se abrió con la radio apagada, alcanza con que haya tema).
function musicaSonando(estado, estacion, pistaAntes) {
    if (!estado || !estado.encendida || estado.estacion !== estacion || !estado.pista) return false;
    return pistaAntes === null || pistaAntes === undefined || estado.pista !== pistaAntes;
}

function iconoDe(nombre, iconos, generico) {
    return (iconos && iconos[nombre]) || generico;
}

// El volumen que muestra el dial después de una respuesta de la radio: lo local manda (las teclas van adelante de
// las respuestas), salvo que sintonizar haya prendido la radio que estaba en 0 (la API la sube a 50).
function volumenTrasRespuesta(local, delServidor, eraSintonizar) {
    return eraSintonizar && local === 0 ? delServidor : local;
}

if (typeof module !== "undefined") {
    module.exports = {
        etiqueta, tooltip, accionDeRueda, crearLimitador, pedidoHttp, parsearRespuesta,
        parsearVoces, idiomaBase, vocesDelIdioma, etiquetaDeVoz, elegirVoz, elegirIdioma, faltante, argumentosNueva,
        mensajeDeError, argumentosMuestra, botonMuestra, rutaDeMuestra, argumentosExaminar, rutaElegida,
        filaDial, teclaDial, crearCola, barraVolumen, iconoDe, volumenTrasRespuesta,
        parsearUrlServidor, idEstacion, planRemoto, estadoRemoto, parsearReceptor, parsearIconos, musicaSonando,
    };
}
