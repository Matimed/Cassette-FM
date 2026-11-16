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
