# La radio acepta los temas que Soloist saltea Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que un tema que Soloist saltea al instante no provoque re-sintonías en bucle, y que otra versión del tema
esperado cuente como ese tema.

**Architecture:** Todo en `ReproductorSpotify.manejar_evento` (rama `track_changed`): antes de medir el desfase,
detectar el salteo rápido y correr el corrimiento; al resolver la pista de un ítem desconocido, compararlo por nombre
con el tema esperado.

**Tech Stack:** Python 3, pytest (`.venv/bin/pytest -q -p no:cacheprovider`).

**Spec:** `docs/superpowers/specs/2026-11-16-soloist-saltea-temas-design.md`

## Global Constraints

- Commits en español, imperativo llano, con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Otro agente trabaja en paralelo: commitear solo archivos propios.
- Nunca mostrar la línea de comando de Soloist.

## Review Focus

1. Un pedido en curso no se ve afectado (con pedidos, sigue la lógica de hoy: plegar / re-sintonía).
2. Varios salteos seguidos (Soloist saltea 3 temas en 2 s) dejan la agenda con lo último que suena, sin re-sintonía.
3. Un salto lento (>2 s) a un tema adelantado sigue re-sintonizando como hoy.
4. Una versión con nombre parecido pero de otro tema (p. ej. «Love» vs «The Power Of Love») no se confunde.

---

### Task 1: Salteo aceptado y versión alternativa

**Files:** Modify `src/cassette_fm/reproductor_spotify.py`; Test `tests/test_reproductor_spotify.py`.

- [ ] **Step 1: Tests que fallan**

```python
def test_soloist_saltea_el_tema_y_la_radio_sigue_con_el_siguiente():
    # en_marcha; X = el tema que empieza en el próximo borde, Y el siguiente; reloj al borde: cambio(X);
    # 0,5 s después cambio(Y) → sin nueva llamada a control (no re-sintoniza); última agenda: corrimiento tal que
    # desfase(nueva, Y, reloj) ≈ 0 (abs 0,01); el pedido de agenda es None
def test_varios_salteos_seguidos_terminan_en_lo_ultimo_que_suena():
    # X, Y, Z en 0,7 s cada uno → sin re-sintonía; desfase(agenda, Z, reloj) ≈ 0
def test_un_salto_lento_a_un_tema_adelantado_resintoniza():
    # cambio(X) en el borde; 10 s después cambio(Y) → re-sintoniza (len(control.llamadas) == 2)
def test_otra_version_del_tema_esperado_cuenta_como_ese():
    # sintonizar; cambio(URI desconocida, nombre "<cancion del esperado> - From Some Soundtrack") → pista_actual es el
    # esperado y la línea registra ("pista", esperado.uri, …)
def test_un_tema_desconocido_con_otro_nombre_no_se_confunde():
    # nombre "Love" cuando el esperado es "T0…": pista_actual.uri es la desconocida
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_reproductor_spotify.py -q -p no:cacheprovider` → FAIL en los nuevos.
- [ ] **Step 3: Implementar** `SALTEO_SEGUNDOS = 2.0` (constante de clase); en `track_changed`, para un tema de la
  agenda sin pedidos en la emisora, si `_cambio_en` fue hace < 2 s y la clave cambió: buscar el tema en
  `transiciones(estacion, ahora - SALTEO_SEGUNDOS)` (hasta 30 transiciones) y, si aparece en `s`,
  `estacion = replace(estacion, corrimiento=estacion.corrimiento - (s - ahora))`, `agenda = (estacion, None)`, sin
  medir desfase. En `_pista_del_item`, para URI desconocida, comparar `nombre.casefold().startswith(cancion.casefold())`
  contra el esperado (si `_primero_pendiente`) o contra el tema que la agenda tiene en curso.
- [ ] **Step 4:** suite completa → PASS.
- [ ] **Step 5: Commit** `git commit -m "Spotify: un tema que Soloist saltea no provoca re-sintonías en bucle"`

### Task 2: Prueba real

- [ ] Reiniciar `cassette-fm` (autorizado), sintonizar Happy Eighties y mirar el log por «Soloist salteó» y
  «se vuelve a sintonizar» durante un rato; documentar en README (sección Spotify) y cerrar CASSETTE-FM-49ga.
