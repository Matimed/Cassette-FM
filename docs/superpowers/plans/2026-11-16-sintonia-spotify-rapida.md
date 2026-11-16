# Sintonía de Spotify más rápida Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apagar shuffle y repeat por el WebSocket de Soloist en vez de la Web API, para que el cambio de emisora de
Spotify tarde ~1,2 s menos.

**Architecture:** `ReproductorSpotify._reproducir` manda los tres comandos locales antes de `ControlSpotify.reproducir`,
que queda solo con el play.

**Tech Stack:** Python 3, pytest (`.venv/bin/pytest -q -p no:cacheprovider`).

**Spec:** `docs/superpowers/specs/2026-11-16-sintonia-spotify-rapida-design.md`

## Global Constraints

- Commits en español, imperativo llano, terminados en `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Hay otro agente trabajando en paralelo: commitear solo los archivos propios (nunca `git add -A`).
- Nunca mostrar la línea de comando de Soloist (`systemctl status`, `ps` con argumentos).

## Review Focus

1. Soloist desconectado al sintonizar: la emisora falla con el motivo de hoy, no queda en silencio.
2. Re-sintonía (`_resintonizar`) también apaga shuffle y repeat antes del play.

---

### Task 1: Shuffle y repeat por Soloist

**Files:**
- Modify: `src/cassette_fm/reproductor_spotify.py` (`_reproducir`), `src/cassette_fm/spotify/control.py` (`_reproducir`)
- Test: `tests/test_reproductor_spotify.py`, `tests/spotify/test_control.py`

- [ ] **Step 1: Tests que fallan**

```python
# tests/test_reproductor_spotify.py
def test_sintonizar_apaga_shuffle_y_repeat_en_soloist_antes_del_play():
    # armar(); el ControlFalso registra en soloist.comandos ("PLAY", {}) al reproducir (para ver el orden)
    # sintonizar → soloist.comandos empieza con set_shuffle/set_repeat_context/set_repeat_track (enabled False)
    # y después el play
def test_resintonizar_tambien_los_apaga():
    # tras un desfase grande que resintoniza, los tres comandos vuelven a ir antes del segundo play

# tests/spotify/test_control.py
def test_reproducir_apaga_shuffle_y_repeat_y_da_play  →  pasa a test_reproducir_solo_da_play:
    # rutas == ["/v1/me/player/play?device_id=D1"]
```

- [ ] **Step 2:** correr los dos archivos → FAIL en los nuevos/cambiados.
- [ ] **Step 3: Implementar.** En `_reproducir` del reproductor, dentro del `try`, después de `_aplicar_volumen()` y
  antes de `self._control.reproducir(...)`, los tres `self._soloist.comando(nombre, enabled=False)` (un `ErrorSpotify`
  cae en el `except` que ya hace `_fallar`). En `ControlSpotify._reproducir`, sacar los dos PUT y actualizar el
  docstring de `reproducir`.
- [ ] **Step 4:** `.venv/bin/pytest -q -p no:cacheprovider` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Shuffle y repeat se apagan por Soloist: la sintonía de Spotify tarda ~1,2 s menos"`

### Task 2: Medición real

- [ ] Reiniciar `cassette-fm` (autorizado) y repetir tres cambios entre emisoras de Spotify con registros temporales
  sin commitear (como la medición del spec); comparar contra ~1,7–2,0 s. Quitar los registros. Actualizar README si
  menciona los PUT de shuffle/repeat.
