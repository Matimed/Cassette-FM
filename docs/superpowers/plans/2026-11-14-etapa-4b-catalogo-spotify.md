# Etapa 4b: login y catálogo de Spotify — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cassette spotify login` deja una sesión de Spotify que se refresca sola, y las emisoras con fuente `spotify`
de `estaciones.json` se convierten en estaciones con sus temas (duración, artistas, álbum, ISRC), con caché por
`snapshot_id`; todavía no suenan (eso es 4c): se omiten de la radio con un aviso que dice cuántos temas tienen listos.

**Architecture:** Paquete nuevo `cassette_fm/spotify/` con tres piezas chicas: `sesion.py` (PKCE, token en disco,
refresh), `api.py` (cliente HTTP mínimo con urllib: auth, reintento por 401/429, paginación) y `catalogo.py` (playlist →
pistas, caché). `emisoras.Catalogo` usa el catálogo de Spotify para las emisoras `spotify`. `Pista` gana `uri` para las
pistas de Spotify (su `clave`).

**Tech Stack:** Python 3.12, urllib, http.server (callback del login), webbrowser, pytest con servidores HTTP falsos.

**Spec:** `docs/superpowers/specs/2026-11-14-etapa-4-spotify-design.md` — secciones "Restricciones" y "3. Catálogo de
Spotify"; de la 6, `cassette spotify login` y la parte de sesión de `cassette spotify estado` (Soloist llega en 4c).

## Global Constraints

- TDD; suite: `CASSETTE_DJ_MODELOS=$HOME/.local/share/cassette-dj/modelos .venv/bin/pytest -q`. Ningún test toca la red real: Spotify se simula con `servidor_http`.
- Commits en español, imperativo, terminando con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Git local en `main`.
- Client ID por defecto `c8f7703801e64bc890d65527fc620248`; redirect `http://127.0.0.1:8888/callback`; PKCE S256, sin client secret.
- Scopes: `user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative`.
- Token en `~/.local/state/cassette-fm/spotify-token.json` (= `rutas.estado.with_name("spotify-token.json")`), modo 600, escritura atómica. Nunca se loguea ni se imprime un token.
- Caché en `~/.cache/cassette-fm/spotify.json` (= `rutas.cache.with_name("spotify.json")`).
- Temas: `GET /v1/playlists/{id}/items?limit=50` (el tema está en `item`, no en `track`), paginado por `next`; se descartan `item` nulo, `type != "track"`, `is_local`, `is_playable == false`.
- Pista de Spotify: `clave = uri`, `duracion = duration_ms / 1000`, `artista` = nombres de `artists` unidos con ", ", `cancion = name`, `album = album.name`, `isrc = external_ids.isrc`, `titulo = "Artista - Canción"`, `fuente = "spotify"`, `ruta = None`.
- Una playlist que no es del usuario no devuelve temas: aviso "la playlist X no es tuya: Spotify no deja leer sus temas; copiala a una playlist propia".
- En 4b las emisoras de Spotify **no** entran a la radio (no hay reproductor): se omiten con un aviso con la cantidad de temas.

## Review Focus

1. El servicio corre días: el access token vence (1 h) → se refresca solo; si Spotify rota el refresh token se guarda el nuevo; si el refresh token fue revocado → aviso claro ("corré `cassette spotify login`") y las emisoras locales siguen. (Tasks 2 y 5)
2. Rescan con Spotify lento, caído o con 429 → no se cuelga (timeouts), usa la caché si la hay y si no omite la emisora con aviso. (Tasks 3 y 4)
3. Playlist con archivos locales, temas no disponibles, episodios o ítems nulos → se saltean; si no queda ningún tema, la emisora se omite con aviso. (Task 4)
4. Puerto 8888 ocupado al hacer login → mensaje claro, código 1. (Task 2)
5. Login cancelado en el navegador (`error=access_denied`) o que nunca vuelve → mensaje claro tras el timeout, código 1, sin dejar un token a medias. (Task 2)

---

### Task 1: Pistas de Spotify y servidor falso compartido

**Files:**
- Modify: `src/cassette_fm/biblioteca.py` (`Pista`)
- Move: fixture `servidor_http` de `tests/dj/conftest.py` a `tests/conftest.py`, agregándole POST
- Test: `tests/test_biblioteca.py`, `tests/test_fixtures.py`

**Interfaces:**
- Produces:
  - `Pista.ruta: Path | None` (sigue siendo el primer campo; `None` en las de Spotify) y campo nuevo al final `uri: str | None = None`. `Pista.clave` = `self.uri` si `fuente == "spotify"`, si no `str(self.ruta)`.
  - `servidor_http` (en `tests/conftest.py`): igual que hoy para GET; además `do_POST` con las mismas reglas, y `s.cuerpos: list[tuple[str, bytes]]` con (ruta, cuerpo) de cada POST. `s.pedidos` sigue siendo `[(ruta, headers)]` para GET y POST. `responder(…, encabezados: dict | None = None)` agrega headers a la respuesta (para `Retry-After`); un `cuerpo` callable puede devolver `(código, cuerpo)` como hoy.

- [ ] **Step 1: Tests que fallan:**

```python
# tests/test_biblioteca.py
def test_la_clave_de_una_pista_de_spotify_es_su_uri():
    p = Pista(ruta=None, duracion=185.877, titulo="Elvis Presley - Can't Help Falling in Love", fuente="spotify",
              artista="Elvis Presley", cancion="Can't Help Falling in Love", uri="spotify:track:44AyOl4qVkzS48vBsbNXaC")
    assert p.clave == "spotify:track:44AyOl4qVkzS48vBsbNXaC"

# tests/test_fixtures.py
def test_servidor_http_acepta_post(servidor_http):
    servidor_http.responder("/api/token", {"ok": True})
    req = urllib.request.Request(servidor_http.url + "/api/token", data=b"a=1", method="POST")
    assert json.loads(urllib.request.urlopen(req).read()) == {"ok": True}
    assert servidor_http.cuerpos == [("/api/token", b"a=1")]
```

- [ ] **Step 2:** correrlos → FAIL.
- [ ] **Step 3:** implementar; los tests de `tests/dj/` siguen usando el fixture (ahora heredado).
- [ ] **Step 4:** suite completa → PASS.
- [ ] **Step 5: Commit** — `Pista de Spotify (clave = URI) y servidor HTTP falso con POST para los tests`.

### Task 2: Sesión de Spotify (PKCE, token y refresh) y `cassette spotify login`

**Files:**
- Create: `src/cassette_fm/spotify/__init__.py`, `src/cassette_fm/spotify/sesion.py`
- Modify: `src/cassette_fm/config.py` (sección `[spotify]` y `Rutas.spotify_token`), `src/cassette_fm/cli.py` (subcomando `spotify login`)
- Test: `tests/spotify/test_sesion.py`, `tests/test_config.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `config.ConfigSpotify` (frozen): `client_id: str = "c8f7703801e64bc890d65527fc620248"`, `puerto_login: int = 8888`, `timeout_segundos: float = 10.0`, `cuentas_url: str = "https://accounts.spotify.com"`, `api_url: str = "https://api.spotify.com/v1"`. `Config.spotify: ConfigSpotify`. Se lee de `[spotify]` del `config.toml` con las validaciones de siempre (texto, entero 1–65535, positivo, URL http/https).
  - `Rutas.spotify_token -> Path` = `self.estado.with_name("spotify-token.json")`; `Rutas.spotify_cache -> Path` = `self.cache.with_name("spotify.json")`.
  - `spotify.sesion.ESCOPOS: str` (el de Global Constraints).
  - `class ErrorSesion(Exception)` — mensaje listo para mostrar.
  - `class Sesion`: `__init__(self, archivo: Path, config: ConfigSpotify, reloj=time.time)`; `token(self, forzar: bool = False) -> str` (lee el archivo en cada llamada; refresca con `grant_type=refresh_token` si vence en menos de 60 s o si `forzar`; guarda el refresh token nuevo si viene; sin archivo → `ErrorSesion("no hay sesión de Spotify: corré cassette spotify login")`; refresh rechazado (400) → `ErrorSesion("la sesión de Spotify venció o fue revocada: corré cassette spotify login")`; red caída → `ErrorSesion("Spotify no responde: …")`); `guardar(self, respuesta: dict) -> None` (agrega `expira` = reloj + `expires_in`; modo 600; atómico).
  - `def login(sesion: Sesion, config: ConfigSpotify, abrir=webbrowser.open, timeout: float = 300) -> None` — genera verificador/desafío PKCE y `state`, levanta `127.0.0.1:{puerto_login}`, abre `{cuentas_url}/authorize?…` con `abrir`, espera `/callback` hasta `timeout`, verifica `state`, cambia el `code` por el token (`grant_type=authorization_code`, `code_verifier`, `client_id`, `redirect_uri`) y llama a `guardar`. Errores → `ErrorSesion` con: "el puerto 8888 está ocupado…", "cancelaste el permiso en Spotify (access_denied)", "no llegó la respuesta de Spotify en 300 s".
  - CLI: `cassette spotify login` → `login(...)`; imprime "Listo: sesión de Spotify guardada." o el `ErrorSesion` a stderr con código 1. No necesita el servicio corriendo.

- [ ] **Step 1: Tests que fallan** (`tests/spotify/__init__.py` vacío). Con `servidor_http` haciendo de `cuentas_url`:

```python
def test_login_completo_guarda_el_token(tmp_path, servidor_http):
    servidor_http.responder("/api/token", {"access_token": "A1", "refresh_token": "R1", "expires_in": 3600})
    cfg = ConfigSpotify(cuentas_url=servidor_http.url, puerto_login=puerto_libre())
    s = Sesion(tmp_path / "t.json", cfg, reloj=lambda: 1000.0)
    def abrir(url):        # hace de navegador: valida la URL y llama al callback con el state recibido
        q = parse_qs(urlparse(url).query)
        assert q["code_challenge_method"] == ["S256"] and q["client_id"] == [cfg.client_id]
        assert q["redirect_uri"] == [f"http://127.0.0.1:{cfg.puerto_login}/callback"] and "playlist-read-private" in q["scope"][0]
        threading.Thread(target=urlopen, args=(f"{q['redirect_uri'][0]}?code=C1&state={q['state'][0]}",)).start()
    login(s, cfg, abrir=abrir, timeout=5)
    assert s.token() == "A1" and oct((tmp_path / "t.json").stat().st_mode)[-3:] == "600"
    (ruta, cuerpo), = servidor_http.cuerpos
    datos = parse_qs(cuerpo.decode())
    assert datos["grant_type"] == ["authorization_code"] and datos["code"] == ["C1"] and "code_verifier" in datos

def test_login_con_state_ajeno_o_cancelado_no_guarda(...): ...   # state distinto → sigue esperando y vence el timeout; error=access_denied → ErrorSesion "cancelaste"; archivo no existe
def test_login_con_el_puerto_ocupado(...): ...                   # socket ocupando el puerto → ErrorSesion "ocupado"
def test_login_sin_respuesta_vence(...): ...                     # abrir no hace nada, timeout=0.5 → ErrorSesion "no llegó"
def test_token_se_refresca_y_guarda_el_refresh_nuevo(tmp_path, servidor_http): ...
    # archivo con expira=1000, reloj=999.5 → refresca (grant_type=refresh_token, refresh_token=R1); respuesta con
    # refresh_token=R2 → el archivo queda con R2; si la respuesta no trae refresh_token, conserva R1
def test_token_vigente_no_llama_a_spotify(...): ...
def test_token_forzado_refresca_aunque_este_vigente(...): ...
def test_sin_sesion_y_refresh_revocado_dicen_que_hacer(...): ...  # sin archivo / 400 invalid_grant → ErrorSesion con "cassette spotify login"
def test_el_token_no_aparece_en_los_mensajes(...): ...            # ningún ErrorSesion contiene "A1" ni "R1"
# tests/test_config.py: [spotify] por defecto y con valores; puerto fuera de rango y url sin http → ErrorConfig
# tests/test_cli.py: `cassette spotify login` con login simulado (monkeypatch) → 0 y "Listo"; con ErrorSesion → 1 y el mensaje
```

- [ ] **Step 2:** correrlos → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `tests/spotify tests/test_config.py tests/test_cli.py` → PASS.
- [ ] **Step 5: Commit** — `Spotify: sesión con PKCE, refresh automático y cassette spotify login`.

### Task 3: Cliente de la API de Spotify

**Files:**
- Create: `src/cassette_fm/spotify/api.py`
- Test: `tests/spotify/test_api.py`

**Interfaces:**
- Consumes: `Sesion.token(forzar)`, `ErrorSesion`, `ConfigSpotify`.
- Produces:
  - `class ErrorSpotify(Exception)` — con `codigo: int | None` (HTTP) y mensaje sin tokens.
  - `class ClienteSpotify`: `__init__(self, sesion: Sesion, config: ConfigSpotify, dormir=time.sleep)`; `get(self, ruta: str, params: dict | None = None) -> dict` (Authorization Bearer; 401 → `token(forzar=True)` y reintenta una vez; 429 → espera `Retry-After` si es ≤ 5 s y reintenta una vez, si no `ErrorSpotify`; otros 4xx/5xx → `ErrorSpotify(codigo=…)` con el `error.message` de Spotify si viene; red/timeout → `ErrorSpotify(codigo=None)`; `ErrorSesion` se convierte en `ErrorSpotify` con su mensaje); `paginas(self, ruta: str, params: dict | None = None) -> Iterator[dict]` (sigue `next` —URL absoluta— mientras exista; cada página es el JSON completo). `ruta` es relativa a `api_url` ("/playlists/x").

- [ ] **Step 1: Tests que fallan** con `servidor_http` como `api_url` y una `Sesion` falsa (`token(forzar)` que cuenta llamadas):

```python
def test_get_manda_el_token(...): ...                  # header Authorization == "Bearer A1"
def test_401_refresca_y_reintenta_una_vez(...): ...    # 1.ª respuesta 401, 2.ª 200 → dict; token(forzar=True) llamado 1 vez; dos 401 → ErrorSpotify(codigo=401)
def test_429_corto_espera_y_reintenta(...): ...        # Retry-After: 2 → dormir(2) y reintento; Retry-After: 60 → ErrorSpotify(codigo=429) sin dormir
def test_error_con_mensaje_de_spotify(...): ...        # 403 {"error": {"status": 403, "message": "Forbidden"}} → codigo 403 y "Forbidden" en el mensaje
def test_timeout_es_error_spotify(...): ...            # demora > timeout → ErrorSpotify(codigo=None)
def test_paginas_sigue_next(...): ...                  # 3 páginas encadenadas por "next" → 3 dicts en orden
def test_sin_sesion_es_error_spotify_con_el_mensaje(...): ...
```

(Respuestas que cambian entre llamadas: `cuerpo` callable que devuelve `(código, cuerpo)` según cuántas veces se llamó. `Retry-After`: `encabezados={"Retry-After": "2"}`.)

- [ ] **Step 2:** FAIL. - [ ] **Step 3:** implementar. - [ ] **Step 4:** `tests/spotify` → PASS.
- [ ] **Step 5: Commit** — `Spotify: cliente de la API con reintentos por 401 y 429 y paginación`.

### Task 4: Catálogo: playlist → pistas, con caché por snapshot

**Files:**
- Create: `src/cassette_fm/spotify/catalogo.py`
- Test: `tests/spotify/test_catalogo.py`

**Interfaces:**
- Consumes: `ClienteSpotify.get/paginas`, `ErrorSpotify`, `Pista`.
- Produces:
  - `class CatalogoSpotify`: `__init__(self, cliente: ClienteSpotify, archivo_cache: Path)`; `pistas(self, playlist: str) -> tuple[Pista, ...]`: pide `GET /playlists/{id}?fields=snapshot_id,name`; si el `snapshot_id` es el de la caché, devuelve las pistas cacheadas sin pedir los temas; si no, recorre `GET /playlists/{id}/items?limit=50` con `paginas`, arma las pistas (reglas de Global Constraints), guarda en la caché `{id: {"snapshot_id", "nombre", "pistas": [...]}}` (atómico) y las devuelve **en el orden de la playlist**. Si Spotify falla (`ErrorSpotify`) y hay caché de esa playlist, loguea WARNING "Spotify no respondió (…): la emisora usa los temas guardados" y devuelve la caché; sin caché, propaga. Un 403/404 en los temas → `ErrorSpotify` con "la playlist «nombre» no es tuya: Spotify no deja leer sus temas; copiala a una playlist propia".
  - `def pista_de(item: dict) -> Pista | None` (pública, para testear el mapeo y los descartes).

- [ ] **Step 1: Tests que fallan:**

```python
ITEM = {"is_local": False, "item": {"type": "track", "uri": "spotify:track:44AyOl4qVkzS48vBsbNXaC",
        "name": "Can't Help Falling in Love", "duration_ms": 185877, "is_playable": True, "is_local": False,
        "artists": [{"name": "Elvis Presley"}], "album": {"name": "Blue Hawaii"},
        "external_ids": {"isrc": "USRC16101350"}}}

def test_pista_de_un_item():
    p = pista_de(ITEM)
    assert (p.clave, p.duracion, p.artista, p.cancion, p.album, p.isrc, p.titulo, p.fuente, p.ruta) == (
        "spotify:track:44AyOl4qVkzS48vBsbNXaC", 185.877, "Elvis Presley", "Can't Help Falling in Love",
        "Blue Hawaii", "USRC16101350", "Elvis Presley - Can't Help Falling in Love", "spotify", None)

@pytest.mark.parametrize("cambio", [{"item": None}, {"is_local": True}, {"item": {**ITEM["item"], "type": "episode"}},
                                    {"item": {**ITEM["item"], "is_playable": False}},
                                    {"item": {**ITEM["item"], "duration_ms": 0}}])
def test_items_que_se_saltean(cambio):
    assert pista_de({**ITEM, **cambio}) is None

def test_varios_artistas_van_con_coma(): ...          # [{"name": "Cardi B"}, {"name": "21 Savage"}] → "Cardi B, 21 Savage"
def test_lee_todas_las_paginas_en_orden_y_cachea(...): ...
def test_mismo_snapshot_no_pide_los_temas(...): ...    # 2.ª llamada: solo el pedido de snapshot
def test_snapshot_nuevo_vuelve_a_leer(...): ...
def test_spotify_caido_usa_la_cache_y_avisa(...): ...  # caplog WARNING "temas guardados"
def test_spotify_caido_sin_cache_propaga(...): ...
def test_playlist_ajena_dice_que_hacer(...): ...       # items → 403 → ErrorSpotify con "no es tuya" y "copiala"
def test_cache_corrupta_se_ignora(...): ...            # archivo con basura → lee de Spotify como si no hubiera caché
```

- [ ] **Step 2:** FAIL. - [ ] **Step 3:** implementar. - [ ] **Step 4:** `tests/spotify` → PASS.
- [ ] **Step 5: Commit** — `Spotify: catálogo de playlists con caché por snapshot_id`.

### Task 5: Emisoras de Spotify en el catálogo, servicio y `cassette spotify estado`

**Files:**
- Modify: `src/cassette_fm/emisoras.py` (`Catalogo`), `src/cassette_fm/servicio.py`, `src/cassette_fm/cli.py`, `README.md`
- Test: `tests/test_emisoras.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `Catalogo.__init__(self, config, rutas, spotify: CatalogoSpotify | None = None, reproduce_spotify: bool = False)`. En `escanear`, para cada emisora `spotify`: sin catálogo (`spotify is None`, solo en tests) → se omite con WARNING; con catálogo, `pistas(id)` → `Estacion(nombre, pistas, fuente="spotify")`; un `ErrorSpotify` (incluye "no hay sesión: corré cassette spotify login", que viene de la sesión) → WARNING "la emisora %r: %s" y se omite; sin pistas → WARNING "la playlist de %r no tiene temas que se puedan escuchar". Si `reproduce_spotify` es falso (4b), las estaciones de Spotify armadas se omiten de la lista con INFO "la emisora %r tiene %d temas de Spotify listos; la reproducción llega en la parte 4c". Los ajustes del DJ de las emisoras Spotify quedan disponibles igual en `configuracion_dj`.
  - `servir`: construye `Sesion(rutas.spotify_token, config.spotify)`, `ClienteSpotify` y `CatalogoSpotify(…, rutas.spotify_cache)` y se los pasa al `Catalogo` (con `reproduce_spotify=False`).
  - CLI `cassette spotify estado` (no necesita el servicio): sesión (`GET /me` → "sesión: <display_name> (premium)" o el error de sesión), y por cada emisora de Spotify de `estaciones.json`: "«Nombre»: N temas (playlist «nombre»)" o el error. Código 0 si la sesión anda, 1 si no.

- [ ] **Step 1: Tests que fallan:**

```python
# tests/test_emisoras.py (CatalogoSpotify falso con dict playlist→pistas o excepción)
def test_catalogo_arma_la_emisora_spotify_y_en_4b_la_omite_con_aviso(...): ...   # INFO con "12 temas" y "4c"; estaciones solo locales
def test_catalogo_con_reproduce_spotify_incluye_la_emisora_en_su_lugar(...): ...  # orden del JSON respetado, fuente == "spotify"
def test_catalogo_error_de_spotify_omite_solo_esa_emisora(...): ...              # ErrorSpotify("no es tuya…") → WARNING con el nombre
def test_catalogo_playlist_sin_temas_avisa(...): ...
def test_catalogo_dj_de_la_emisora_spotify_disponible(...): ...
# tests/test_cli.py
def test_spotify_estado_muestra_sesion_y_emisoras(...): ...   # con servidor_http como api_url y token en disco
def test_spotify_estado_sin_sesion_sale_con_1(...): ...
```

- [ ] **Step 2:** FAIL. - [ ] **Step 3:** implementar; README: sección "Spotify" (requisitos: Premium, playlist propia; `cassette spotify login`, `cassette spotify estado`; en 4b las emisoras de Spotify se leen pero todavía no suenan).
- [ ] **Step 4:** suite completa → PASS.
- [ ] **Step 5: Commit** — `Emisoras de Spotify: el catálogo lee las playlists (todavía no suenan) y cassette spotify estado`.

## Verificación con el usuario (al final)

`cassette spotify login` (autorizar en el navegador), `cassette spotify estado` (tiene que mostrar tu cuenta y, si
agregás la emisora "Sing" al JSON, sus 12 temas), `cassette rescan` y en el log: "Sing tiene 12 temas de Spotify
listos". Un segundo rescan no vuelve a bajar los temas (mismo snapshot).
