# Borrar una emisora — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cassette borrar "Nombre" [--si]` saca la emisora de `estaciones.json` (preguntando antes) y la radio la
deja de mostrar.

**Architecture:** Lo puro (buscar por nombre, describir, escribir la lista) en `emisora_nueva.py`, junto a lo de
`cassette nueva`; el comando en `cli.py` pregunta, guarda y pide el rescan.

**Tech Stack:** Python 3, argparse, pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-borrar-emisora-design.md`

## Global Constraints

- Español rioplatense; commits en español con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` y rutas
  explícitas. Tests sin tocar la config real (helper `_nueva` de `tests/test_cli.py`).
- Textos exactos: `¿Borro «{nombre}» ({descripcion})? (s/N) `, `No se borró nada.`,
  `✗ {nombre} · ya no está en estaciones.json`, `La radio no está corriendo: el cambio se ve al prenderla.`

## Review Focus

- Sin terminal y sin `--si` no se queda esperando (test en Task 2).
- Un nombre con otra capitalización o espacios alrededor la encuentra (test en Task 1).
- El archivo queda igual salvo la emisora borrada (otros campos, orden y acentos; test en Task 2).
- La emisora que suena se borra: la radio pasa a otra (lo hace `Radio.rescan`; se prueba en real).
- Borrar la última emisora: queda `[]` y la radio se apaga (test en Task 2: el archivo queda `[]`).

---

### Task 1: buscar, describir y escribir

**Files:** Modify `src/cassette_fm/emisora_nueva.py`; Test `tests/test_emisora_nueva.py`

**Interfaces:**
- Produces: `buscar(emisoras: list[dict], nombre: str) -> int` (índice; `ErrorConfig` "no hay ninguna emisora que
  se llame «X» (hay: A, B)").
- Produces: `describir(emisora: dict) -> str` → `"Spotify"` o `"carpeta /ruta"` (otra cosa: `"fuente desconocida"`).
- Produces: `escribir(archivo: Path, emisoras: list[dict]) -> None` (la escritura atómica que hoy hace `guardar`;
  `guardar` pasa a usarla).

- [ ] **Step 1: tests que fallan**

```python
def test_buscar_sin_mayusculas_ni_espacios():
    emisoras = [{"nombre": "Happy Eighties"}, {"nombre": " Más Gasolina F.M. "}]
    assert buscar(emisoras, "  más gasolina f.m.") == 1
    with pytest.raises(ErrorConfig, match="Happy Eighties"):
        buscar(emisoras, "Sing")

def test_describir():
    assert describir({"fuente": {"spotify": "x"}}) == "Spotify"
    assert describir({"fuente": {"carpeta": "/m/Rock"}}) == "carpeta /m/Rock"
    assert describir({}) == "fuente desconocida"

def test_escribir_la_lista_tal_cual(tmp_path):
    archivo = tmp_path / "estaciones.json"
    escribir(archivo, [{"nombre": "Más"}])
    assert json.loads(archivo.read_text(encoding="utf-8")) == [{"nombre": "Más"}] and "Más" in archivo.read_text()
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_emisora_nueva.py -q` → FAIL (import).
- [ ] **Step 3:** implementar. **Step 4:** PASS. **Step 5: commit** `Emisoras: buscar por nombre, describir y escribir la lista`.

### Task 2: `cassette borrar`

**Files:** Modify `src/cassette_fm/cli.py`, `README.md` (junto a `cassette nueva`); Test `tests/test_cli.py`

**Interfaces:** Consumes Task 1. Produces `cassette borrar NOMBRE [--si]`.

- [ ] **Step 1: tests que fallan** (helper `_nueva`: estaciones.json con Happy Eighties; `monkeypatch` de
  `builtins.input` y de `sys.stdin.isatty`)

```python
def test_borrar_pregunta_borra_y_rescanea(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    r, rutas = _nueva(monkeypatch, tmp_path, servidor_http)
    r.emisoras.write_text(_json.dumps(HAPPY + [{"nombre": "Sing", "fuente": {"spotify": "x"}, "dj": {"voz": "dora"}}],
                                      ensure_ascii=False))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda texto: print(texto, end="") or "S")
    assert main(["borrar", "  sing "]) == 0
    assert _json.loads(r.emisoras.read_text()) == HAPPY
    salida = capsys.readouterr().out
    assert "¿Borro «Sing» (Spotify)? (s/N)" in salida and "✗ Sing · ya no está en estaciones.json" in salida
    assert [ruta for ruta, _ in rutas] == ["/rescan"]

def test_borrar_con_otra_respuesta_no_borra(...):        # input → "n": archivo igual, "No se borró nada.", rc 1, sin rescan
def test_borrar_sin_terminal_pide_si(...):               # isatty → False, sin --si: rc 1, stderr menciona --si, archivo igual
def test_borrar_con_si_no_pregunta(...):                 # input lanza AssertionError si se llama; --si borra la última: archivo "[]"
def test_borrar_una_que_no_existe_lista_las_que_hay(...):  # stderr menciona Happy Eighties, rc 1
def test_borrar_con_la_radio_apagada_lo_dice(...):        # _llamar lanza cli._ServicioCaido: rc 0, "no está corriendo"
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_cli.py -k borrar -q` → FAIL (`invalid choice`).
- [ ] **Step 3:** implementar `_borrar(args, rutas, puerto) -> int` y el despacho en `main` junto a `nueva`.
- [ ] **Step 4:** PASS; `pytest -q` → verde.
- [ ] **Step 5: commit** `cassette borrar: saca una emisora (preguntando antes) y la radio la deja de mostrar`.

### Task 3: prueba real y contexto

- [ ] **Step 1:** crear una emisora de prueba con `cassette nueva "Borrame" <link de Sing> --voz dora`, después
  `cassette borrar "borrame"` respondiendo `n` (no borra) y otra vez respondiendo `s`: Expected: la radio vuelve a
  la primera emisora y `cassette list` ya no la muestra. Volver a sintonizar lo que sonaba antes.
- [ ] **Step 2:** `docs/project-context.md` (una frase y el enlace a la spec); commit `Contexto: cassette borrar`.
