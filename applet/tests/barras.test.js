"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const B = require("../cassette-fm@cassette-fm/barras.js");

test("alturas: una por columna, entre 1 y las filas, y siempre la misma para el mismo instante", () => {
  for (const ms of [0, 90, 1234, 99999]) {
    const a = B.alturas(ms, 4, 5);
    assert.equal(a.length, 4);
    for (const n of a) assert.ok(Number.isInteger(n) && n >= 1 && n <= 5, `fuera de rango: ${n}`);
    assert.deepEqual(a, B.alturas(ms, 4, 5));
  }
});

test("alturas: cada columna sube y baja con el tiempo y no todas van a la par", () => {
  const vistas = [new Set(), new Set(), new Set(), new Set()];
  let parejas = 0;
  for (let ms = 0; ms < 4000; ms += 90) {
    const a = B.alturas(ms, 4, 5);
    a.forEach((n, i) => vistas[i].add(n));
    if (new Set(a).size === 1) parejas++;
  }
  for (const v of vistas) assert.ok(v.size >= 3, "una columna casi no se mueve");
  assert.ok(parejas < 15, "las columnas se mueven todas juntas");
});

test("suena: solo con la radio prendida y el monitor local sin silenciar", () => {
  assert.equal(B.suena({ encendida: true }), true);
  assert.equal(B.suena({ encendida: true, monitor_local: true }), true);
  assert.equal(B.suena({ encendida: true, monitor_local: false }), false);
  assert.equal(B.suena({ encendida: false }), false);
  assert.equal(B.suena(null), false);
});

test("medidas: los puntos entran en el alto del ícono del panel", () => {
  for (const tam of [16, 22, 24, 32, 48]) {
    const m = B.medidas(tam, 4, 5);
    assert.ok(m.punto >= 1 && m.hueco >= 1, `tamaño ${tam}`);
    assert.ok(m.alto <= tam && m.alto >= tam * 0.6, `alto ${m.alto} para ${tam}`);
    assert.ok(m.ancho > 0 && m.ancho <= tam * 1.2);
  }
});
