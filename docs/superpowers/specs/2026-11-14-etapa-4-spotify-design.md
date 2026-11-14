# Etapa 4: emisoras en JSON y Spotify como fuente — diseño

Fecha: 14/11/2026. Diseño general: [`2026-11-13-cassette-fm-design.md`](2026-11-13-cassette-fm-design.md) (etapa 4 y
"Evolución prevista: estaciones como objetos"). Beans: `CASSETTE-FM-4yzi` (épica), `waxf`, `jbqg`; `40h0` queda
afuera (ver No objetivos).

## Intención

Hoy cada emisora es una subcarpeta de `~/Música` y suena desde archivos descargados. El usuario quiere que una emisora
pueda ser **una playlist de Spotify** (tiene Premium) y que todo lo construido —agenda determinista, DJ, planificador,
locutor, rescan, CLI, applet, atajos— funcione igual con las dos fuentes. Para eso las emisoras dejan de derivarse de
las carpetas y pasan a definirse en un **JSON**: nombre, fuente (una carpeta en cualquier ruta o una playlist de
Spotify) y los ajustes del DJ de esa emisora. Spotify, además, trae metadata (ISRC, álbum, artistas) que el DJ
aprovecha.

## Objetivos

- Emisoras definidas en `~/.config/cassette-fm/estaciones.json`, con fuente `carpeta` (cualquier ruta) o `spotify`
  (link o URI de una playlist), y los ajustes del DJ de cada una.
- Migración automática: si el JSON no existe, se genera con las subcarpetas actuales de la raíz de música y los
  `[dj.estaciones."X"]` del `config.toml`. El usuario no pierde nada.
- Una emisora de Spotify se comporta como una local: misma agenda determinista (orden mezclado propio, no el de la
  playlist), se entra con el tema empezado en el segundo que corresponde, el DJ habla entre temas con ducking.
- Entre temas de Spotify no hay cortes (Spotify encadena la lista que le pasamos).
- Al sintonizar una emisora de Spotify se tolera una demora corta, tapada con un **sonido de sintonización**.
- El rescan relee carpetas y playlists.
- El DJ usa la metadata de Spotify (artistas, título, álbum, ISRC) para sus pedidos.

## No objetivos

- Comandos o API para crear y borrar emisoras (`CASSETTE-FM-40h0`): el JSON se edita a mano. Queda para después.
- Pedidos de temas a Spotify, skip, búsquedas (etapa 7).
- Playlists que el usuario no creó ni colabora (ver Restricciones).
- Varias cuentas de Spotify, o más de un usuario.
- Mezclar fuentes dentro de una misma emisora (una emisora es una carpeta **o** una playlist).

## Anti-objetivos (sería un fracaso aunque "funcione")

- Que la radio le pelee el control de reproducción a otro dispositivo de Spotify del usuario.
- Que una emisora de Spotify suene mucho más fuerte o más bajo que una local al mismo volumen de la radio.
- Que el cambio de tema dentro de una emisora de Spotify tenga silencios o cortes perceptibles.
- Que una falla de Spotify (red, Soloist caído o vencido) deje la radio colgada o en un estado raro: se apaga y avisa,
  igual que hoy cuando una emisora local no puede sonar.
- Que el cambio de las emisoras a JSON altere la agenda de las emisoras locales existentes (mismo orden de temas, mismas
  firmas del planificador).

## Restricciones (verificadas el 14/11/2026)

- **API de Spotify en modo desarrollo** (cambios de febrero de 2026): la app necesita un dueño con Premium, hasta 5
  usuarios, y **los temas de una playlist solo se devuelven si el usuario la creó o colabora**; las que sigue
  (incluidas las editoriales) devuelven solo metadata. Para usar una de esas hay que copiarla a una propia.
  Los temas vienen en `GET /playlists/{id}/items` (campo `item`, ya no `track`), con `duration_ms`, `artists`,
  `album` (`name`, `release_date`), `external_ids.isrc`, `is_playable`, `is_local`; la página admite `limit=50`
  (probado). Se removieron `popularity` y otros campos que no usamos.
  Fuente: <https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide>.
- **App de desarrollador ya creada** por el usuario: Client ID `c8f7703801e64bc890d65527fc620248`, redirect
  `http://127.0.0.1:8888/callback`, Web API + Web Playback SDK. Login con **PKCE** (sin client secret). Scopes:
  `user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative`.
- **Spotify Soloist** (cliente oficial sin interfaz, agosto 2026): binario x86_64 de
  `https://soloist-builds.spotifycdn.com/soloist_release_x86_64.tar.gz`; **cada build vence a los 90 días** (sale con
  código 10); requiere una API key de desarrollador (el usuario la guardó en `~/.config/cassette-fm/soloist.key`, modo
  600; no se loguea ni se imprime) y **emparejarse una vez** desde la app de Spotify en la misma red (`--pair`); la
  sesión queda en su directorio de datos. API WebSocket local (`-w 127.0.0.1:PUERTO`, sin autenticación: solo
  loopback). Visto en vivo en el spike (`soloist ctl trace`): `playback_changed`/`playback_state` con `buffering` →
  `playing`, `track_changed`, `position_sync`, `device_changed` con `is_active`, `options_changed`, `queue_changed`
  (entradas con `source`: `context`, `queue` o `autoplay`) y `volume_changed`. Lo no visto (p. ej. el comportamiento de
  una lista `uris` muy larga) se verifica al empezar 4c. Sale de audio por PipeWire (o PulseAudio); su stream se llama "Spotify" y no trae el PID.
  Docs: <https://developer.spotify.com/documentation/soloist>.
- **Premium reproduce en un dispositivo a la vez.**
- La PC tiene 13 GiB de RAM con ~2 GiB libres cuando corre el LLM: el reproductor tiene que ser liviano.
- Desarrollo con TDD; git local en `main`; commits en español.

## Enfoques considerados

### Reproductor de Spotify (medido en la PC del usuario el 14/11, `spikes/spotify/`)

| | Web Playback SDK en Chrome oculto | **Spotify Soloist** (elegido) |
|---|---|---|
| RAM (PSS) | ~520–580 MB, 13–14 procesos | **~41–51 MB, 1 proceso** |
| CPU sonando | ~4 % | ~1 % |
| Sintonía (de pausa a sonido) | ~1,1–1,4 s | **~0,4 s** |
| Cambio de volumen | ~0,1 s | ~0,03 s |
| Arranca en `position_ms` pedido | sí | sí (por la Web API, sin `seek`) |
| Cambio de tema | sin huecos medibles | igual |
| Costos | ventana de Chrome escondida, Widevine, autoplay | build vence cada 90 días, API key, emparejar una vez |

Al oído el usuario no notó diferencias; se decide por recursos y latencia. El SDK queda como plan B documentado.
Hallazgos de la prueba que valen para el diseño: hay que **apagar shuffle y repeat** en el dispositivo antes de
sintonizar (si no, la cuenta los aplica y suena otro tema); la curva de volumen de Soloist es empinada (80→40 ≈ −15 dB,
80→20 ≈ −35 dB, 80→5 ≈ −72 dB) y un salto instantáneo de volumen se siente brusco: se necesita rampa.

### Orden de los temas

- A. `context_uri` de la playlist: Spotify encadena en el orden de la playlist; la emisora se comportaría distinto de
  una local.
- **B. (elegido)** Lista de temas (`uris`) en el orden de la agenda determinista + cola: igual de suave, y la emisora
  es idéntica a una local para el planificador, el desfase y el futuro skip.

### Emisoras

Seguir derivándolas de carpetas (descartado: no admite Spotify ni carpetas fuera de la raíz) vs. **JSON** (elegido,
era el plan desde el diseño general).

## Diseño

### 1. Emisoras en JSON

`~/.config/cassette-fm/estaciones.json` (respeta `XDG_CONFIG_HOME`), una lista en el orden en que se rotan:

```json
[
  {"nombre": "Happy Eighties", "fuente": {"carpeta": "/home/matimed/Música/Happy Eighties"},
   "dj": {"idioma": "en", "voz": "am_puck"}},
  {"nombre": "Sing", "fuente": {"spotify": "https://open.spotify.com/playlist/4iHcTVQbU4QvIJV5Xao0fs"},
   "dj": {"idioma": "en", "voz": "af_heart"}}
]
```

- `nombre` obligatorio y único (comparación sin mayúsculas ni acentos, como `Radio._buscar`). `fuente` con exactamente
  una clave: `carpeta` (ruta absoluta o con `~`) o `spotify` (link `open.spotify.com/playlist/…` con o sin `?si=`, o
  URI `spotify:playlist:…`). `dj` opcional: las mismas claves que hoy acepta `[dj.estaciones."X"]` (todas las de
  `ConfigDJ`), validadas con las mismas reglas y mensajes; lo que falta sale de `[dj]` del `config.toml`.
- El **orden** es el del archivo (hoy es alfabético). La migración lo escribe alfabético para no cambiar nada.
- **Migración**: si el archivo no existe, se genera una vez con cada subcarpeta de `raiz_musica` que hoy forma una
  estación (mismas reglas de `biblioteca.escanear`: no ocultas, nombre UTF-8 válido, con audio) y su
  `[dj.estaciones."X"]`. Se loguea qué se migró. Después, si el `config.toml` todavía tiene `[dj.estaciones]`, se
  ignora con una advertencia ("ya se usan los ajustes de estaciones.json"). `raiz_musica` solo se usa para migrar.
- Un JSON inválido (sintaxis, campo desconocido, nombre repetido, fuente rara) es un error de configuración claro, como
  hoy con el `config.toml`; una emisora individual que no se puede leer (carpeta inexistente, playlist inaccesible)
  **no** tumba a las demás: se omite con una advertencia.
- La función que hoy devuelve la configuración del DJ por estación (`configuracion_dj`) pasa a leer del JSON; el resto
  del código no se entera.

### 2. Pistas y emisoras con dos fuentes

- `Pista` ya tiene `fuente` ("local"); se agrega "spotify". Su identidad deja de ser `ruta: Path` y pasa a ser una
  **clave de texto**: la ruta (como hoy, `str(ruta)`) para las locales, la URI `spotify:track:…` para las de Spotify.
  Todo lo que hoy usa `str(pista.ruta)` como identidad (orden base de la agenda, `pista_destino` del locutor, firmas del
  planificador) usa la clave. **Para las locales la clave es exactamente `str(ruta)`**, así el orden de la agenda y las
  firmas no cambian (anti-objetivo).
- `Estacion` sabe su tipo de fuente (para elegir reproductor) y conserva `pistas` con duración, título, artista,
  canción, álbum e ISRC.

### 3. Catálogo de Spotify

- **Login**: `cassette spotify login` abre el navegador (PKCE contra `127.0.0.1:8888/callback`) y guarda el token con
  refresh en `~/.local/state/cassette-fm/spotify-token.json` (modo 600). El access token se refresca solo. Sin token
  válido, las emisoras de Spotify se omiten con una advertencia que dice qué comando correr.
- **Playlist → emisora**: `GET /playlists/{id}/items` paginado (50 por página). Se descartan los ítems que no son
  temas (episodios, `null`), los `is_local` y los `is_playable == false`. Pista: clave = URI, duración =
  `duration_ms / 1000`, artista = nombres de `artists` unidos con ", " (como los tags locales), canción = `name`, álbum =
  `album.name`, ISRC = `external_ids.isrc`, título = "Artista - Canción".
- **Caché** en `~/.cache/cassette-fm/spotify.json` por playlist, con su `snapshot_id`: el rescan pide primero solo el
  `snapshot_id` y baja los temas solo si cambió. Si Spotify no responde, se usa la caché (y la emisora suena igual si
  Soloist anda); sin caché y sin respuesta, la emisora se omite con una advertencia.
- Una playlist que no es del usuario devuelve metadata sin temas: advertencia explícita ("la playlist X no es tuya: Spotify
  no deja leer sus temas; copiala a una playlist propia").

### 4. Reproducción con Soloist

- **Servicio** `cassette-soloist.service` (systemd de usuario), siempre encendido: `soloist -n "cassette-fm" -k <key>
  -D ~/.local/share/cassette-fm/soloist -C ~/.cache/cassette-fm/soloist -w 127.0.0.1:<puerto> -i <volumen inicial>`. La
  key se lee del archivo al arrancar (no va escrita en la unidad). El binario vive en
  `~/.local/share/cassette-fm/soloist/bin/`.
- **Reproductor de Spotify** con la misma interfaz que el `Reproductor` actual (`sintonizar`, `detener`, `posicion`,
  `volumen`, `atenuar(factor, segundos)`, `asegurar`, `pista_actual`, `al_cambiar_pista`, `al_fallar`). La radio elige
  el reproductor según la fuente de la emisora; al cambiar entre fuentes, detiene el otro (mpv `stop` o Soloist
  `pause`). El locutor (voz del DJ) sigue en su propio mpv.
- **Sintonizar** una emisora de Spotify:
  1. mpv de música deja de sonar la emisora anterior y pasa a reproducir en bucle el **sonido de sintonización** (un clip
     corto de estática que se distribuye con el proyecto o se genera; el constructor elige).
  2. Por la Web API: apagar shuffle y repeat en el dispositivo de Soloist; `PUT /me/player/play?device_id=…` con
     `uris` = los próximos temas de la agenda (el actual primero) y `position_ms` = el segundo que corresponde según el
     reloj virtual **al momento de mandar la orden** (más la latencia típica medida, ~0,4 s, si mejora la precisión).
  3. Cuando el WebSocket de Soloist avisa `playing` del tema esperado, la estática baja con un fundido corto
     (~0,3 s) y mpv se detiene.
  4. Si en ~10 s no suena: se considera falla (ver más abajo).
- **Mientras suena**: la radio **no usa la cola de Spotify** (es de la cuenta, no del dispositivo, y no se puede vaciar
  por la API). En la sintonía se manda una lista `uris` larga (del orden de 100 temas, unas horas de música; el máximo
  real se verifica en 4c) y, si alguna vez se acerca al final, se vuelve a mandar en un borde de tema (lista nueva +
  posición 0). Cada `track_changed` actualiza `pista_actual` y dispara `al_cambiar_pista` (eso ancla al locutor y mide
  el desfase, como con mpv).
- **La cola queda para el usuario** (decisión del usuario, 14/11): si mientras suena una emisora de Spotify agrega un
  tema a la cola desde la app, Spotify lo toca a continuación y la radio **lo deja sonar** (no lo corta ni re-sintoniza
  en el medio). Un tema que no es el que espera la agenda no dispara intervenciones del DJ (el locutor ya se ancla a la
  clave del tema destino). Cuando la lista sigue, el desfase acumulado se corrige en el borde como cualquier desfase.
  *Futuro (etapa de pedidos, no ahora)*: tratar esos temas como **peticiones del público** — una inserción en la agenda
  que corre el reloj de esa emisora y descarta las intervenciones planificadas que pisa; al cambiar de emisora lo
  encolado se pierde. Por eso se eligió no usar la cola: este diseño lo deja servido.
- **Desfase**: al empezar cada tema se compara con el reloj virtual (la función `desfase` de la agenda). Si supera una
  tolerancia (unos pocos segundos; valor del constructor), se re-sintoniza en ese borde con la Web API (lista nueva +
  posición), sin estática. Es raro: Spotify encadena con precisión.
- **Posición**: se interpola con los `position_sync` del WebSocket (no se consulta la Web API en cada pedido).
- **Volumen**: la radio maneja 0–100 con la curva de mpv (cúbica). Para que una emisora de Spotify suene igual que una
  local al mismo volumen, se usa una **tabla de calibración** volumen-de-radio → volumen-de-Soloist, medida durante la
  implementación con la misma técnica del spike (grabar el stream y comparar dB) contra una emisora local normalizada.
  La normalización de volumen propia de Spotify queda como esté en la cuenta; la calibración se hace con ella activa.
  *Decisión de diseño*: si Soloist al 100 suena más bajo que una local, primero se sube el volumen del stream "Spotify"
  en PipeWire por encima del 100 % hasta donde no sature; si aun así no alcanza, se acepta que en volúmenes muy altos
  Spotify quede algo más bajo. Las emisoras locales no se tocan.
- **Ducking del DJ**: `atenuar` hace la misma rampa que el `Reproductor` local (pasos de ~50 ms; bajada ~0,4 s, subida
  ~1 s) mandando `set_volume` por el WebSocket. `nivel_musica_con_voz` (hoy en escala de mpv, 0,6 ≈ −13 dB) se traduce
  con la misma calibración para que la caída en dB sea la misma.
- **Control de la cuenta**:
  - Si **otro dispositivo toma la reproducción** mientras suena una emisora de Spotify (`device_changed` con
    `is_active: false`), la radio **se apaga** y avisa ("Spotify se está escuchando en otro dispositivo"). No pelea por
    el control.
  - Si el usuario **sintoniza** una emisora de Spotify, la radio toma el control aunque otro dispositivo esté sonando
    (fue su decisión).
  - Si alguien elige "cassette-fm" como parlante desde la app de Spotify sin que la radio lo haya pedido: **no se
    controla** (el usuario no lo va a usar así). La radio solo escucha a Soloist mientras tiene sintonizada una emisora
    de Spotify; lo único que importa es que al sintonizar recupere el control.
  - Que lo que suena en la radio entre al historial, las recomendaciones y el resumen anual de la cuenta **es aceptable**
    (usuario, 14/11).
- **Fallas** (sin red, token vencido sin refresh posible, Soloist caído o vencido, playlist vacía, no suena en ~10 s):
  `al_fallar` → la radio se apaga y avisa con el motivo, como hoy. El reproductor intenta reconectar el WebSocket en la
  próxima sintonía.

### 5. DJ y planificador

- El planificador, el locutor y el registro de intervenciones trabajan con la clave de la pista; no distinguen fuentes.
- El pedido al servicio DJ lleva artista, título, álbum e ISRC de la pista de Spotify (ya existen esos campos). Con el
  ISRC, MusicBrainz encuentra la grabación exacta. El álbum pasa por el filtro de recopilatorios ya existente.
- El ducking usa `atenuar` del reproductor que corresponda; el locutor se ancla al `track_changed` real.

### 6. Rescan, CLI, applet

- `cassette rescan` relee `estaciones.json`, las carpetas y las playlists (con la caché por `snapshot_id`), y avisa al
  planificador como hoy.
- CLI, API, applet y atajos siguen trabajando con nombres de emisora. `cassette estado` muestra además la fuente
  (carpeta o Spotify).
- Nuevos: `cassette spotify login` y `cassette spotify estado` (sesión de Spotify, Soloist corriendo/emparejado/activo,
  días hasta que vence el build — avisa si faltan menos de 14).

### 7. Instalación y mantenimiento

- `scripts/instalar-spotify.sh`: baja Soloist, instala la unidad systemd, recuerda dónde poner la API key, lanza el
  emparejamiento (`--pair`, el usuario elige el dispositivo desde el celular) y corre `cassette spotify login`.
- `scripts/actualizar-soloist.sh`: baja el build nuevo, reemplaza el binario y reinicia el servicio. (La URL es fija.)
- `config.toml`, sección nueva `[spotify]`: `client_id` (por defecto el de la app del usuario), puerto del WebSocket de
  Soloist, ruta de la API key, timeouts. Todo con valores por defecto razonables.

## Lo que queda al constructor

- Cómo se parte en planes (sugerencia: 4a emisoras en JSON + clave de pista, sin Spotify; 4b catálogo y login de
  Spotify; 4c reproducción con Soloist, estática, calibración y DJ).
- El sonido de sintonización (clip incluido o generado), la tolerancia de desfase para re-sintonizar, cuántos temas
  por delante mantener en la cola y cuántos mandar en `uris`, el puerto del WebSocket.
- Cómo se reparte la responsabilidad entre Web API y WebSocket de Soloist, siempre que se respete lo medido
  (`position_ms` por la Web API; volumen y eventos por el WebSocket).
- La forma exacta de la tabla de calibración y cómo se mide (con un script de la etapa, no a mano).

## Verificación con el usuario (al final, juntos)

Migración del JSON sin cambios audibles en las emisoras locales; una emisora de Spotify (la playlist "Sing") sonando con
estática al sintonizar, temas encadenados sin cortes, DJ hablando con ducking suave y volumen parejo con las locales;
poner música en el celular y ver que la radio se apaga y avisa; rescan después de agregar un tema a la playlist.
