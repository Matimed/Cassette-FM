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

if (typeof module !== "undefined") {
    module.exports = { etiqueta, tooltip, accionDeRueda, crearLimitador, pedidoHttp, parsearRespuesta };
}
