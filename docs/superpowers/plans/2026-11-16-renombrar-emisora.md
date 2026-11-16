# Renombrar una emisora — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cassette renombrar "viejo" "nuevo"` cambia el nombre en `estaciones.json` y, si sonaba, la radio sigue en
esa emisora con el nombre nuevo.

**Architecture:** Reusa `buscar`, `chequear_nombre` y `escribir` de `emisora_nueva.py`; todo el comando en `cli.py`.

**Tech Stack:** Python 3, argparse, pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-renombrar-emisora-design.md`

## Global Constraints

- Español rioplatense; commits en español con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` y rutas
  explícitas. Tests con el helper `_nueva` de `tests/test_cli.py` (sin config real).
- Textos exactos: `✎ {viejo} → {nuevo}`, `«{nombre}» ya se llama así.`,
  `La radio no está corriendo: el cambio se ve al prenderla.`
- El usuario pidió saltear la revisión independiente final.

## Review Focus

- Renombrar la emisora que suena: la radio la vuelve a sintonizar con el nombre nuevo (test en Task 1).
- Cambiar solo mayúsculas no choca consigo misma (test en Task 1).
- El nombre nuevo de otra emisora (sin importar mayúsculas) da error sin tocar nada (test en Task 1).
- Los demás campos y el orden de la lista quedan igual (test en Task 1).
- Radio apagada: el archivo cambia y se avisa (test en Task 1).

---

### Task 1: `cassette renombrar`

**Files:** Modify `src/cassette_fm/cli.py`, `README.md` (junto a `cassette borrar`); Test `tests/test_cli.py`

**Interfaces:** Consumes `emisora_nueva.leer_crudo`, `buscar`, `chequear_nombre`, `escribir`. Produces
`cassette renombrar VIEJO NUEVO` (`_renombrar(args, rutas, puerto) -> int`).

- [ ] **Step 1: tests que fallan** — helper `_renombrar(monkeypatch, tmp_path, servidor_http, sonando=None)`:
  estaciones.json = `HAPPY + [SING]`; `cli._llamar` anota `(ruta, cuerpo)` y devuelve un estado con
  `estacion = sonando or "Happy Eighties"` (y en `/sintonizar`, la del cuerpo).

```python
def test_renombrar_cambia_solo_el_nombre(...):          # main(["renombrar", " SING ", "Cantemos"]) == 0;
    # el json == HAPPY + [dict(SING, nombre="Cantemos")]; "✎ Sing → Cantemos" en la salida; rutas == ["/estado", "/rescan"]
def test_renombrar_la_que_suena_la_vuelve_a_sintonizar(...):   # sonando="Sing": rutas == ["/estado", "/rescan",
    # "/sintonizar"] con cuerpo {"estacion": "Cantemos"}; "▶ Cantemos" en la salida
def test_renombrar_solo_las_mayusculas(...):           # "sing" → "SING": rc 0, nombre "SING"
def test_renombrar_igual_no_toca_nada(...):            # "sing" → "Sing": rc 0, "«Sing» ya se llama así.", sin llamadas
def test_renombrar_a_un_nombre_de_otra_emisora(...):   # "Sing" → "happy eighties": rc 1, stderr con «Happy Eighties», archivo igual
def test_renombrar_a_un_nombre_vacio(...):             # "Sing" → "  ": rc 1, archivo igual
def test_renombrar_una_que_no_existe(...):             # "Nada" → "X": rc 1, stderr con Happy Eighties
def test_renombrar_con_la_radio_apagada(...):          # _llamar lanza _ServicioCaido: rc 0, archivo cambiado, mensaje
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_cli.py -k renombrar -q` → FAIL (`invalid choice`).
- [ ] **Step 3:** implementar. `GET /estado` antes de escribir (`_ServicioCaido` → recordar que la radio no corre y
  no llamar más); después de escribir, `/rescan` y, si `estado["encendida"]` y `estado["estacion"]` era el nombre
  viejo, `/sintonizar`; imprimir `_linea_estado` de la última respuesta.
- [ ] **Step 4:** PASS; `pytest -q` → verde. **Step 5: commit** `cassette renombrar: le cambia el nombre a una emisora`.

### Task 2: prueba real y contexto

- [ ] **Step 1:** con la radio en Happy Eighties: `cassette nueva "Renombrame" <link de Sing> --voz dora` (queda
  sonando), `cassette renombrar "renombrame" "Renombrada"`: Expected `✎ Renombrame → Renombrada` y
  `▶ Renombrada · Spotify`; después `cassette borrar --si renombrada` y volver a sintonizar Happy Eighties;
  `estaciones.json` igual al de antes.
- [ ] **Step 2:** `docs/project-context.md` y README; commit `Contexto: cassette renombrar`.
