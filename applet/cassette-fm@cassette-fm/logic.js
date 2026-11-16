// Lógica pura del applet de cassette-fm: sin dependencias de Cinnamon, así se prueba con Node.
// En Cinnamon se usa como `AppletDir.logic.<función>`; en Node, con require().

function etiqueta(estado, mostrarEstacion) {
    if (!estado || !estado.encendida || !mostrarEstacion) return "";
    return estado.estacion || "";
}

function tooltip(estado) {
    if (!estado) return "cassette-fm no responde";
    if (!estado.encendida) return "Apagada · volumen " + estado.volumen;
    let lineas = [estado.estacion];
    if (estado.pista) lineas.push(estado.pista);
    lineas.push("Volumen " + estado.volumen);
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

function pedidoHttp(metodo, ruta, cuerpo) {
    let cabeceras = metodo + " " + ruta + " HTTP/1.0\r\nHost: 127.0.0.1\r\n";
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

// Los argumentos de `cassette nueva`, uno por elemento: el proceso se lanza sin shell.
function argumentosNueva(nombre, link, seleccion) {
    const args = ["nueva", nombre, link];
    if (seleccion.voz) args.push("--voz", seleccion.voz.alias);
    if (seleccion.idioma !== "") args.push("--idioma", seleccion.idioma);
    return args;
}

function mensajeDeError(codigo, stdout, stderr) {
    const error = (stderr || "").trim();
    if (error) return error;
    const lineas = (stdout || "").split("\n").map((l) => l.trim()).filter((l) => l);
    if (lineas.length) return lineas[lineas.length - 1];
    return "cassette nueva terminó con error (código " + codigo + ")";
}

if (typeof module !== "undefined") {
    module.exports = {
        etiqueta, tooltip, accionDeRueda, crearLimitador, pedidoHttp, parsearRespuesta,
        parsearVoces, idiomaBase, vocesDelIdioma, etiquetaDeVoz, elegirVoz, elegirIdioma, faltante, argumentosNueva,
        mensajeDeError,
    };
}
