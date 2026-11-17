# Sintonía instantánea — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que cambiar de emisora de Spotify suene en ~0,3 s aunque la Web API tarde segundos.

**Architecture:** `ReproductorSpotify._reproducir` manda primero `play` del primer tema por el WebSocket de Soloist,
deja un seek pendiente que `manejar_evento` dispara al llegar el `track_changed` de ese tema, y después del `play`
de la Web API corrige la posición con otro `seek` si hizo falta.

**Tech Stack:** Python 3, pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-sintonia-local-design.md`

## Global Constraints

- Español rioplatense; commits en español con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Comandos de Soloist exactos: `comando("play", uri=<uri>)`, `comando("seek", position_ms=<int>)`.
- Umbral de corrección: 1 s (era 0,5 s; subido tras la prueba real). Las re-sintonías no usan el `play` local.
- Nunca mostrar los argumentos del proceso de Soloist (`ps`, `systemctl status`): la clave va ahí.

## Review Focus

- Una sintonía nueva mientras la anterior espera a la Web API: el seek y la corrección de la vieja no salen (Task 1).
- `track_changed` de otro tema (lo que sonaba antes) con el seek pendiente: no hay seek (Task 1).
- El `play` local falla: sigue la Web API, sin seek ni falla de la emisora (Task 1).
- Spotify rápido: un solo seek (el del `track_changed`), sin corrección extra (Task 1).
- La estática se corta con el `play` local (el test existente de "suena cuando llega el tema esperado" sigue igual).

---

### Task 1: el primer tema por Soloist

**Files:** Modify `src/cassette_fm/reproductor_spotify.py` (`_reproducir` con `local: bool`, `sintonizar` lo pide,
`_resintonizar` no; `self._seek_pendiente: tuple[int, str, Callable[[], int]] | None`; `manejar_evento` dispara el
seek fuera del lock); `README.md` (sección Spotify: una línea). Test: `tests/test_reproductor_spotify.py`.

- [ ] **Step 1: tests que fallan**
  - `test_sintonizar_suena_primero_por_soloist`: con `control.antes` que anota `soloist.comandos` al momento del play
    de la API → ya incluye `("play", {"uri": primero})`.
  - `test_al_cargar_el_tema_local_salta_a_la_posicion`: después de `sintonizar`, `reloj.t += 0.3`,
    `manejar_evento(cambio(primero))` → último comando `("seek", {"position_ms": pos_inicial + 300})` (con `uris=1`
    para no depender de la lista; `pos_inicial` = la del play de la API menos lo que avanzó el reloj).
  - `test_track_changed_de_otro_tema_no_salta`: `cambio(otra_uri)` → ningún `seek`.
  - `test_spotify_lento_corrige_la_posicion_al_volver`: `control.antes` avanza `reloj.t += 3` → después de
    `sintonizar`, hay un `seek` con la posición de ese momento.
  - `test_spotify_rapido_no_agrega_otro_seek`: `control.antes` dispara `manejar_evento(cambio(primero))` y avanza 0,2 s
    → exactamente un `seek`.
  - `test_una_sintonia_nueva_anula_el_seek_de_la_vieja`: con `Diferido` (el control que demora el play), sintonizar A,
    sintonizar B, recién ahí llega `cambio(primero_de_A)` y vuelve el play de A → ningún seek de A.
  - `test_si_el_play_local_falla_sigue_por_la_api`: Soloist que lanza `ErrorSpotify` solo en `play` → la API recibe
    la lista, sin fallas ni seek.
  - `test_la_resintonia_no_usa_el_play_local`: forzar `_resintonizar()` → ningún `("play", …)` nuevo en Soloist.
- [ ] **Step 2:** `pytest tests/test_reproductor_spotify.py -q` → los nuevos FAIL.
- [ ] **Step 3:** implementar. **Step 4:** PASS + `pytest -q`. **Step 5: commit**
  `Spotify: el primer tema suena por Soloist mientras la lista viaja por la Web API`.

### Task 2: prueba real y contexto

- [ ] **Step 1:** reiniciar `cassette-fm`; cambiar de emisora varias veces con `cassette next` y medir con un
  observador del WebSocket (como `soloist-play/sondear.py`) el tiempo de la orden al `playing` y la posición; mirar
  en el log los `Spotify tardó …` de esos cambios.
- [ ] **Step 2:** el usuario escucha cambios reales (atajos y dial) y dice si el microcorte molesta.
- [ ] **Step 3:** `docs/project-context.md` (una frase y el enlace); commit `Contexto: sintonía instantánea`.
