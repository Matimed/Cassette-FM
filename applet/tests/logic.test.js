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
