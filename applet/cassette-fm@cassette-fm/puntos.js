// Las barritas de puntos del panel (suenan = la radio está prendida y se oye): la lógica pura, sin Cinnamon, así se prueba con Node.
// En Cinnamon se usa como `AppletDir.puntos.<función>`; en Node, con require(). El dibujo (Cairo) vive en applet.js.

// Cada columna mezcla dos ondas con su propio ritmo (radianes por milisegundo): se mueven parecido a un ecualizador.
const RITMOS = [[0.0052, 0.0113], [0.0063, 0.0097], [0.0057, 0.0131], [0.0071, 0.0089], [0.0047, 0.0107]];

// Cuántos puntos prendidos (de 1 a `filas`, contando desde abajo) tiene cada columna en el instante `ms`.
function alturas(ms, columnas, filas) {
    const salida = [];
    for (let c = 0; c < columnas; c++) {
        const [a, b] = RITMOS[c % RITMOS.length];
        const fase = c * 2.1;
        const v = 0.5 + 0.3 * Math.sin(ms * a + fase) + 0.2 * Math.sin(ms * b + fase * 1.3);    // entre 0 y 1
        salida.push(1 + Math.round(v * (filas - 1)));
    }
    return salida;
}

// Qué muestra el panel: "apagada" (el casete), "suena" (las barritas) o "muteada" (solo el nombre: con el bus de audio la
// radio puede estar prendida pero silenciada en este monitor, y ahí no hay nada que animar).
function modo(estado) {
    if (!estado || !estado.encendida) return "apagada";
    return estado.monitor_local === false ? "muteada" : "suena";
}

// Tamaño de los puntos para un ícono de `tam` px de alto: la grilla ocupa el 62 % (queda aire arriba y abajo, sin tocar el
// borde del panel) y los puntos van separados.
function medidas(tam, columnas, filas) {
    const alto = tam * 0.62;
    const hueco = Math.max(1, alto / (filas + (filas - 1) * 0.5) / 2);
    const punto = (alto - (filas - 1) * hueco) / filas;
    return { punto, hueco, alto, ancho: columnas * punto + (columnas - 1) * hueco };
}

if (typeof module !== "undefined") module.exports = { alturas, modo, medidas };
