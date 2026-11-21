"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../cassette-fm@cassette-fm/logic.js");

const encendida = { encendida: true, estacion: "Regueton 2000", pista: "Zion & Lennox - Ahora", volumen: 70 };
const apagada = { encendida: false, estacion: "Regueton 2000", pista: null, volumen: 70 };

test("etiqueta: nombre de la estación solo si está encendida y se pide mostrarla", () => {
  assert.equal(L.etiqueta(encendida, true), "Regueton 2000");
  assert.equal(L.etiqueta(apagada, true), "");
  assert.equal(L.etiqueta(encendida, false), "");
  assert.equal(L.etiqueta(null, true), "");
  assert.equal(L.etiqueta(undefined, true), "");
});

test("tooltip: encendida con pista", () => {
  assert.equal(L.tooltip(encendida), "Regueton 2000\nZion & Lennox - Ahora\nVolumen 70");
});

test("tooltip: encendida sin pista omite la línea", () => {
  assert.equal(L.tooltip({ ...encendida, pista: null }), "Regueton 2000\nVolumen 70");
});

test("tooltip: apagada", () => {
  assert.equal(L.tooltip(apagada), "Apagada · volumen 70");
});

test("tooltip: servicio caído", () => {
  assert.equal(L.tooltip(null), "cassette-fm no responde");
  assert.equal(L.tooltip(undefined), "cassette-fm no responde");
});

test("accionDeRueda", () => {
  assert.equal(L.accionDeRueda("up"), "siguiente");
  assert.equal(L.accionDeRueda("down"), "anterior");
  assert.equal(L.accionDeRueda("left"), null);
  assert.equal(L.accionDeRueda(undefined), null);
});

test("crearLimitador deja pasar una acción por ventana, contada desde la última aceptada", () => {
  const ok = L.crearLimitador(150);
  assert.equal(ok(1000), true);
  assert.equal(ok(1100), false);
  assert.equal(ok(1160), true);
  assert.equal(ok(1200), false);
});

test("pedidoHttp: línea inicial y cabeceras", () => {
  const p = L.pedidoHttp("GET", "/estado");
  assert.ok(p.startsWith("GET /estado HTTP/1.0\r\n"));
  assert.ok(p.includes("Host: 127.0.0.1\r\n"));
  assert.ok(!p.includes("Content-Length"));
  assert.ok(p.endsWith("\r\n\r\n"));
});

test("pedidoHttp: Content-Length en bytes UTF-8, no en caracteres", () => {
  const cuerpo = { estacion: "Ñandú" };
  const json = JSON.stringify(cuerpo);
  const p = L.pedidoHttp("POST", "/sintonizar", cuerpo);
  assert.ok(p.startsWith("POST /sintonizar HTTP/1.0\r\n"));
  assert.ok(Buffer.byteLength(json) > json.length);
  assert.ok(p.includes(`Content-Length: ${Buffer.byteLength(json)}\r\n`));
  assert.ok(p.includes("Content-Type: application/json\r\n"));
  assert.ok(p.endsWith("\r\n\r\n" + json));
});

test("parsearRespuesta: 200 con JSON", () => {
  const r = L.parsearRespuesta('HTTP/1.0 200 OK\r\nContent-Type: application/json; charset=utf-8\r\n\r\n{"encendida":true}');
  assert.deepEqual(r, { codigo: 200, datos: { encendida: true } });
});

test("parsearRespuesta: error del servicio", () => {
  const r = L.parsearRespuesta('HTTP/1.0 409 Conflict\r\n\r\n{"error":"No hay estaciones"}');
  assert.equal(r.codigo, 409);
  assert.equal(r.datos.error, "No hay estaciones");
});

test("parsearRespuesta: basura, vacío o JSON cortado no lanzan", () => {
  const caido = { codigo: 0, datos: null };
  assert.deepEqual(L.parsearRespuesta(""), caido);
  assert.deepEqual(L.parsearRespuesta("basura"), caido);
  assert.deepEqual(L.parsearRespuesta(undefined), caido);
  assert.deepEqual(L.parsearRespuesta('HTTP/1.0 200 OK\r\n\r\n{"encendida":tr'), caido);
  assert.deepEqual(L.parsearRespuesta("HTTP/1.0 200 OK\r\n\r\n"), caido);
});

test("parsearRespuesta: acepta cuerpo con acentos", () => {
  const r = L.parsearRespuesta('HTTP/1.0 200 OK\r\n\r\n{"estacion":"Música Ñandú"}');
  assert.equal(r.datos.estacion, "Música Ñandú");
});

const VOCES = [
  { alias: "puck", voz: "am_puck", idioma: "en", emisoras: ["Happy Eighties"] },
  { alias: "emma", voz: "bf_emma", idioma: "en-gb", emisoras: [] },
  { alias: "dora", voz: "ef_dora", idioma: "es", emisoras: ["Sing", "Otra"] },
];

test("parsearVoces", () => {
  assert.deepEqual(L.parsearVoces(JSON.stringify(VOCES) + "\n"), VOCES);
  assert.equal(L.parsearVoces("usage: cassette [-h]"), null);
  assert.equal(L.parsearVoces('{"alias": "x"}'), null);
  assert.equal(L.parsearVoces('[{"alias": "x"}]'), null);
  assert.equal(L.parsearVoces(null), null);
});

test("vocesDelIdioma: en-gb cuenta como inglés; Cualquiera las muestra todas", () => {
  assert.deepEqual(L.vocesDelIdioma(VOCES, "en").map(v => v.alias), ["puck", "emma"]);
  assert.deepEqual(L.vocesDelIdioma(VOCES, "es").map(v => v.alias), ["dora"]);
  assert.equal(L.vocesDelIdioma(VOCES, "").length, 3);
});

test("etiquetaDeVoz", () => {
  assert.equal(L.etiquetaDeVoz(VOCES[1]), "emma");
  assert.equal(L.etiquetaDeVoz(VOCES[2]), "dora · Sing, Otra");
  assert.equal(L.etiquetaDeVoz(null), "Al azar");
});

test("elegir una voz con Cualquiera fija su idioma; con idioma elegido no lo cambia", () => {
  assert.deepEqual(L.elegirVoz({ idioma: "", voz: null }, VOCES[1]), { idioma: "en", voz: VOCES[1] });
  assert.deepEqual(L.elegirVoz({ idioma: "es", voz: null }, VOCES[2]), { idioma: "es", voz: VOCES[2] });
  assert.deepEqual(L.elegirVoz({ idioma: "es", voz: VOCES[2] }, null), { idioma: "es", voz: null });
});

test("cambiar a un idioma que la voz no habla la vuelve a Al azar", () => {
  assert.deepEqual(L.elegirIdioma({ idioma: "", voz: VOCES[2] }, "en"), { idioma: "en", voz: null });
  assert.deepEqual(L.elegirIdioma({ idioma: "en", voz: VOCES[1] }, "en"), { idioma: "en", voz: VOCES[1] });
  assert.deepEqual(L.elegirIdioma({ idioma: "es", voz: VOCES[2] }, ""), { idioma: "", voz: VOCES[2] });
});

test("faltante", () => {
  assert.equal(L.faltante("  ", "x"), "Falta el nombre");
  assert.equal(L.faltante("Sing", " "), "Falta el link de la playlist");
  assert.equal(L.faltante("Sing", "x"), null);
});

test("argumentosNueva: cada dato es un argumento, sin shell; las opciones antes de -- y del nombre", () => {
  const link = "https://open.spotify.com/playlist/4iH?si=b5";
  assert.deepEqual(L.argumentosNueva("Sing «2»", link, { idioma: "", voz: null }), ["nueva", "--", "Sing «2»", link]);
  assert.deepEqual(L.argumentosNueva("S", link, { idioma: "es", voz: VOCES[2] }),
                   ["nueva", "--voz", "dora", "--idioma", "es", "--", "S", link]);
  assert.deepEqual(L.argumentosNueva("S", link, { idioma: "en", voz: null }), ["nueva", "--idioma", "en", "--", "S", link]);
  // un nombre que empieza con - no es una opción (con -h, cassette mostraría la ayuda y saldría con 0)
  assert.deepEqual(L.argumentosNueva("-h", link, { idioma: "", voz: null }), ["nueva", "--", "-h", link]);
});

test("mensajeDeError", () => {
  assert.equal(L.mensajeDeError(1, "", "la playlist está vacía\n"), "la playlist está vacía");
  assert.equal(L.mensajeDeError(1, "✓ Sing (3 temas)\nLa emisora quedó guardada…\n\n", ""), "La emisora quedó guardada…");
  assert.equal(L.mensajeDeError(2, "", ""), "cassette nueva terminó con error (código 2)");
});

test("argumentosMuestra: voz, su idioma y el nombre escrito", () => {
  assert.deepEqual(L.argumentosMuestra(VOCES[1], "  Sing 2 "),
                   ["muestra", "--voz=emma", "--idioma=en-gb", "--radio=Sing 2"]);
  // un nombre que empieza con - va pegado a su opción: argparse no lo toma como otra opción
  assert.deepEqual(L.argumentosMuestra(VOCES[2], "-h"), ["muestra", "--voz=dora", "--idioma=es", "--radio=-h"]);
});

test("botonMuestra", () => {
  assert.deepEqual(L.botonMuestra(null, "quieto"), { texto: "▶", activo: false });
  assert.deepEqual(L.botonMuestra(VOCES[2], "quieto"), { texto: "▶", activo: true });
  assert.deepEqual(L.botonMuestra(VOCES[2], "generando"), { texto: "…", activo: false });
  assert.deepEqual(L.botonMuestra(VOCES[2], "sonando"), { texto: "■", activo: true });
});

test("rutaDeMuestra", () => {
  assert.equal(L.rutaDeMuestra("/home/x/.cache/cassette-dj/muestras/ab.wav\n"), "/home/x/.cache/cassette-dj/muestras/ab.wav");
  assert.equal(L.rutaDeMuestra("algo raro"), null);
  assert.equal(L.rutaDeMuestra(""), null);
});

test("argumentosNueva con logo: --icono pegado, antes del --", () => {
  const link = "https://open.spotify.com/playlist/4iH?si=b5";
  assert.deepEqual(L.argumentosNueva("S", link, { idioma: "es", voz: VOCES[2] }, "/home/x/Mis imágenes/á.png"),
                   ["nueva", "--voz", "dora", "--idioma", "es", "--icono=/home/x/Mis imágenes/á.png", "--", "S", link]);
  assert.deepEqual(L.argumentosNueva("S", link, { idioma: "", voz: null }, null), ["nueva", "--", "S", link]);
});

test("argumentosExaminar y rutaElegida", () => {
  assert.deepEqual(L.argumentosExaminar(), ["--file-selection", "--title=Logo de la emisora",
                                            "--file-filter=Imágenes | *.png *.jpg *.jpeg *.svg *.PNG *.JPG *.JPEG *.SVG"]);
  assert.equal(L.rutaElegida(0, "/a/b c.png\n"), "/a/b c.png");
  assert.equal(L.rutaElegida(1, ""), null);
  assert.equal(L.rutaElegida(0, "\n"), null);
});

// --- el dial ---

const fila = (f) => f.map(e => e.nombre + ":" + e.desplazamiento).join(" ");

test("filaDial: con pocas, todas, la actual en 0 y la que sobra a la derecha", () => {
  assert.equal(fila(L.filaDial(["A", "B", "C"], "B")), "A:-1 B:0 C:1");
  assert.equal(fila(L.filaDial(["A", "B", "C", "D"], "A")), "D:-1 A:0 B:1 C:2");
  assert.equal(fila(L.filaDial(["A"], "A")), "A:0");
  assert.deepEqual(L.filaDial([], null), []);
});

test("filaDial: con más de 7, 3 a cada lado, circular", () => {
  const ocho = ["A", "B", "C", "D", "E", "F", "G", "H"];
  assert.equal(fila(L.filaDial(ocho, "A")), "F:-3 G:-2 H:-1 A:0 B:1 C:2 D:3");
  assert.equal(fila(L.filaDial(ocho, "H")), "E:-3 F:-2 G:-1 H:0 A:1 B:2 C:3");
});

test("filaDial: sin actual, la primera en el centro", () => {
  assert.equal(fila(L.filaDial(["A", "B", "C"], null)), "C:-1 A:0 B:1");
  assert.equal(fila(L.filaDial(["A", "B", "C"], "Borrada")), "C:-1 A:0 B:1");
});

test("teclaDial", () => {
  assert.equal(L.teclaDial("Left"), "anterior");
  assert.equal(L.teclaDial("Right"), "siguiente");
  assert.equal(L.teclaDial("Up"), "subir");
  assert.equal(L.teclaDial("Down"), "bajar");
  assert.equal(L.teclaDial("Escape"), "cerrar");
  assert.equal(L.teclaDial("a"), null);
});

test("crearCola: uno a la vez, y al terminar solo el último que se pidió", () => {
  const enviados = [];
  const cola = L.crearCola((d) => enviados.push(d));
  cola.pedir(1); cola.pedir(2); cola.pedir(3);
  assert.deepEqual(enviados, [1]);
  cola.listo();
  assert.deepEqual(enviados, [1, 3]);
  cola.listo();
  assert.deepEqual(enviados, [1, 3]);
  cola.pedir(4);
  assert.deepEqual(enviados, [1, 3, 4]);
});

test("barraVolumen", () => {
  // un cuadrado por cada 5 %
  assert.equal(L.barraVolumen(60), "▮".repeat(12) + "▱".repeat(8) + " 60");
  assert.equal(L.barraVolumen(5), "▮" + "▱".repeat(19) + " 5");
  assert.equal(L.barraVolumen(100), "▮".repeat(20) + " 100");
  assert.equal(L.barraVolumen(0), "Apagada");
});

test("iconoDe", () => {
  assert.equal(L.iconoDe("Sing", { "Power F.M.": "/p.png" }, "/g.png"), "/g.png");
  assert.equal(L.iconoDe("Power F.M.", { "Power F.M.": "/p.png" }, "/g.png"), "/p.png");
  assert.equal(L.iconoDe("X", undefined, "/g.png"), "/g.png");
});

test("volumenTrasRespuesta: solo sintonizar con la radio apagada adopta el volumen de la radio", () => {
  assert.equal(L.volumenTrasRespuesta(0, 50, true), 50);     // ▶ con la radio apagada: prende en 50
  assert.equal(L.volumenTrasRespuesta(0, 5, false), 0);      // respuesta vieja de /volumen 5 con el 0 en camino
  assert.equal(L.volumenTrasRespuesta(30, 60, true), 30);    // lo local manda si no estaba en 0
});

test("teclaDial: Enter también cierra", () => {
  assert.equal(L.teclaDial("Return"), "cerrar");
});

// --- modo remoto ---

const status = { codigo: 200, datos: { encendida: true, estacion: "B", pista: "Artista - Tema", estaciones: ["A", "B", "C"],
                                       fuente: "spotify", segundo: 3.5, iconos: {} } };
const receptor = { escuchando: true, volumen: 5, error: null };

test("pedidoHttp: sin host ni clave queda igual que siempre", () => {
  assert.equal(L.pedidoHttp("GET", "/estado"), "GET /estado HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n");
});

test("pedidoHttp: con host y clave agrega Host y Authorization", () => {
  const p = L.pedidoHttp("POST", "/station/A", undefined, "100.104.222.41", "secreta");
  assert.equal(p, "POST /station/A HTTP/1.0\r\nHost: 100.104.222.41\r\nAuthorization: Bearer secreta\r\n\r\n");
});

test("parsearUrlServidor", () => {
  assert.deepEqual(L.parsearUrlServidor("http://100.104.222.41:8765"), { host: "100.104.222.41", puerto: 8765 });
  assert.deepEqual(L.parsearUrlServidor("http://100.104.222.41:9000/"), { host: "100.104.222.41", puerto: 9000 });
  assert.deepEqual(L.parsearUrlServidor(" http://mi-pc "), { host: "mi-pc", puerto: 8765 });
  for (const mala of ["https://x:8765", "100.1.1.1:8765", "", "http://", "http://a b:1", "http://x:99999", null, undefined])
    assert.equal(L.parsearUrlServidor(mala), null, String(mala));
});

test("idEstacion codifica para la URL", () => {
  assert.equal(L.idEstacion("Más Gasolina F.M."), "M%C3%A1s%20Gasolina%20F.M.");
  assert.equal(L.idEstacion("A/B"), "A%2FB");
  assert.equal(L.idEstacion("100%"), "100%25");
  assert.equal(L.idEstacion("¿Qué?"), "%C2%BFQu%C3%A9%3F");
});

test("planRemoto: estado y sintonía van al servidor", () => {
  assert.deepEqual(L.planRemoto("/estado", undefined, status.datos, receptor),
                   { destino: "servidor", metodo: "GET", ruta: "/status" });
  assert.deepEqual(L.planRemoto("/sintonizar", { estacion: "A/B" }, status.datos, receptor),
                   { destino: "servidor", metodo: "POST", ruta: "/station/A%2FB" });
  assert.deepEqual(L.planRemoto("/sintonizar", {}, status.datos, receptor), { destino: "ninguno" });
});

test("planRemoto: siguiente y anterior circulan con la lista", () => {
  const e = status.datos;                      // actual: B
  assert.equal(L.planRemoto("/siguiente", undefined, e, receptor).ruta, "/station/C");
  assert.equal(L.planRemoto("/anterior", undefined, e, receptor).ruta, "/station/A");
  assert.equal(L.planRemoto("/siguiente", undefined, { ...e, estacion: "C" }, receptor).ruta, "/station/A");
  assert.equal(L.planRemoto("/anterior", undefined, { ...e, estacion: "A" }, receptor).ruta, "/station/C");
  assert.equal(L.planRemoto("/siguiente", undefined, { ...e, estacion: "Borrada" }, receptor).ruta, "/station/A");
  assert.equal(L.planRemoto("/anterior", undefined, { ...e, estacion: "Borrada" }, receptor).ruta, "/station/C");
  assert.deepEqual(L.planRemoto("/siguiente", undefined, { estaciones: [] }, receptor), { destino: "ninguno" });
  assert.deepEqual(L.planRemoto("/siguiente", undefined, null, receptor), { destino: "ninguno" });
});

test("planRemoto: encendido y volumen van al receptor local", () => {
  const args = (ruta, cuerpo, r = receptor) => L.planRemoto(ruta, cuerpo, status.datos, r).argumentos;
  assert.equal(L.planRemoto("/alternar", undefined, status.datos, receptor).destino, "receptor");
  assert.deepEqual(args("/alternar"), ["off"]);
  assert.deepEqual(args("/alternar", undefined, { escuchando: false, volumen: 5 }), ["on"]);
  assert.deepEqual(args("/encender"), ["on"]);
  assert.deepEqual(args("/volumen", { delta: -10 }), ["volume", "0"]);
  assert.deepEqual(args("/volumen", { delta: 200 }), ["volume", "100"]);
  assert.deepEqual(args("/volumen", { valor: 40 }), ["volume", "40"]);
  assert.deepEqual(args("/volumen", { valor: 400 }), ["volume", "100"]);
  assert.deepEqual(L.planRemoto("/volumen", {}, status.datos, receptor), { destino: "ninguno" });
});

test("planRemoto: elegir emisora con cero oyentes y sin escuchar prende el receptor después", () => {
  const sin = { ...status.datos, oyentes: 0 };
  const nadie = { escuchando: false, volumen: 70, error: null };
  const planes = [L.planRemoto("/sintonizar", { estacion: "C" }, sin, nadie), L.planRemoto("/siguiente", undefined, sin, nadie),
                  L.planRemoto("/anterior", undefined, sin, nadie)];
  assert.deepEqual(planes.map((p) => p.ruta), ["/station/C", "/station/C", "/station/A"]);
  for (const p of planes) {
    assert.equal(p.destino, "servidor");
    assert.equal(p.metodo, "POST");
    assert.deepEqual(p.despues, ["on"]);
  }
});

test("planRemoto: con otros oyentes, ya escuchando o sin dato de oyentes no hay despues", () => {
  const nadie = { escuchando: false, volumen: 70, error: null };
  const casos = [L.planRemoto("/sintonizar", { estacion: "C" }, { ...status.datos, oyentes: 1 }, nadie),
                 L.planRemoto("/sintonizar", { estacion: "C" }, { ...status.datos, oyentes: 0 }, receptor),
                 L.planRemoto("/siguiente", undefined, status.datos, nadie),
                 L.planRemoto("/anterior", undefined, { ...status.datos, oyentes: 2 }, nadie)];
  for (const plan of casos) assert.equal("despues" in plan, false);
});

test("planRemoto: lo que edita o no existe no hace nada", () => {
  for (const r of ["/dj/modo", "/rescan", "/monitor", "/silenciar", "/apagar", "/otra"])
    assert.deepEqual(L.planRemoto(r, {}, status.datos, receptor), { destino: "ninguno" }, r);
});

test("estadoRemoto: lo local manda en encendido y volumen, lo demás es del servidor", () => {
  const e = L.estadoRemoto(status, receptor, "100.104.222.41");
  assert.equal(e.encendida, true);
  assert.equal(e.volumen, 5);
  assert.equal(e.estacion, "B");
  assert.deepEqual(e.estaciones, ["A", "B", "C"]);
  assert.equal(e.aviso, undefined);
});

test("estadoRemoto: la radio principal apagada se avisa solo si se está escuchando", () => {
  const apagadaLejos = { codigo: 200, datos: { ...status.datos, encendida: false } };
  assert.match(L.estadoRemoto(apagadaLejos, receptor, "h").aviso, /principal está apagada/);
  assert.equal(L.estadoRemoto(apagadaLejos, { escuchando: false, volumen: 5 }, "h").aviso, undefined);
});

test("estadoRemoto: clave rechazada, servidor inalcanzable y error del audio", () => {
  const sinClave = L.estadoRemoto({ codigo: 401, datos: { error: "no autorizado" } }, receptor, "100.1.1.1");
  assert.equal(sinClave.aviso, "clave rechazada");
  assert.deepEqual(sinClave.estaciones, []);
  const caido = L.estadoRemoto({ codigo: 0, datos: null }, receptor, "100.1.1.1");
  assert.equal(caido.aviso, "no alcanzo a la radio en 100.1.1.1");
  assert.deepEqual(caido.estaciones, []);
  const sinAudio = L.estadoRemoto(status, { escuchando: false, volumen: 5, error: "sin conexión" }, "h");
  assert.match(sinAudio.aviso, /audio: sin conexión/);
});

test("tooltip: agrega el aviso como última línea", () => {
  assert.equal(L.tooltip({ ...encendida, aviso: "clave rechazada" }),
               "Regueton 2000\nZion & Lennox - Ahora\nVolumen 70\nclave rechazada");
  assert.equal(L.tooltip({ ...apagada, aviso: "no alcanzo a la radio en h" }),
               "Apagada · volumen 70\nno alcanzo a la radio en h");
});

test("parsearReceptor: la salida de lan_receiver.py status --json", () => {
  assert.deepEqual(L.parsearReceptor('{"escuchando": true, "volumen": 40, "error": null}\n'),
                   { escuchando: true, volumen: 40, error: null });
  assert.deepEqual(L.parsearReceptor('{"escuchando": false, "volumen": 0, "error": "clave rechazada"}'),
                   { escuchando: false, volumen: 0, error: "clave rechazada" });
  for (const mala of ["", "no es json", "[]", '{"escuchando": "si"}', '{"escuchando": true}', null, undefined])
    assert.equal(L.parsearReceptor(mala), null, String(mala));
});

test("estadoRemoto: los logos locales reemplazan a las URLs y solo quedan los que el servidor sigue publicando", () => {
  const conLogos = { codigo: 200, datos: { ...status.datos, iconos: { A: "/icon/A?v=1", B: "/icon/B?v=1" } } };
  const locales = { A: "/cache/a.png", B: "/cache/b.png", Vieja: "/cache/v.png" };
  const e = L.estadoRemoto(conLogos, receptor, "h", locales);
  assert.deepEqual(e.iconos, { A: "/cache/a.png", B: "/cache/b.png" });
  assert.deepEqual(L.estadoRemoto(conLogos, receptor, "h").iconos, {});
  assert.deepEqual(L.estadoRemoto({ codigo: 0, datos: null }, receptor, "h", locales).iconos, {});
});

test("parsearIconos: la salida de lan_receiver.py icons", () => {
  assert.deepEqual(L.parsearIconos('{"A": "/cache/a.png"}\n'), { A: "/cache/a.png" });
  assert.deepEqual(L.parsearIconos("{}"), {});
  for (const mala of ["", "x", "[]", '{"A": 3}', "null", null, undefined]) assert.equal(L.parsearIconos(mala), null, String(mala));
});

test("musicaSonando: la emisora pedida ya tiene un tema distinto del que había", () => {
  const ya = { encendida: true, estacion: "B", pista: "Nuevo - Tema", volumen: 50 };
  assert.equal(L.musicaSonando(ya, "B", "Viejo - Tema"), true);
  assert.equal(L.musicaSonando({ ...ya, pista: "Viejo - Tema" }, "B", "Viejo - Tema"), false);   // sigue el tema viejo
  assert.equal(L.musicaSonando({ ...ya, pista: null }, "B", "Viejo - Tema"), false);               // todavía carga
  assert.equal(L.musicaSonando({ ...ya, estacion: "A" }, "B", "Viejo - Tema"), false);
  assert.equal(L.musicaSonando({ ...ya, encendida: false }, "B", null), false);
  assert.equal(L.musicaSonando(ya, "B", null), true);                                              // al abrir con la radio apagada
  assert.equal(L.musicaSonando(null, "B", null), false);
});
