# Configuración (referencia)

Dónde vive cada archivo y qué significa cada clave. Para el orden en que conviene tocarlas está
[`setup.md`](setup.md); las claves del DJ están en [`dj.md`](dj.md). **Todas las claves son opcionales**: sin ningún
archivo de configuración la radio funciona con los valores por defecto.

Después de tocar `config.toml` hay que reiniciar el servicio (`systemctl --user restart cassette-fm`). Después de tocar
`estaciones.json` alcanza con `cassette rescan`.

## Dónde vive cada cosa

Se respetan `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME` y `XDG_DATA_HOME`; abajo, los valores por defecto.

| Archivo | Qué es | Lo escribe |
|---|---|---|
| `~/.config/cassette-fm/config.toml` | ajustes de la radio (esta página) | vos |
| `~/.config/cassette-fm/estaciones.json` | las emisoras | vos, o `cassette nueva/borrar/renombrar/icono` |
| `~/.config/cassette-fm/iconos/` | logos de las emisoras | `cassette icono` |
| `~/.config/cassette-fm/soloist.key` | API key de Soloist (modo 600, **secreta**) | vos |
| `~/.config/cassette-fm/lan.token` | clave de oyente de la LAN (`cassette lan`) | la radio |
| `~/.config/cassette-fm/nube.token` | clave de esta PC para el relay (`cassette nube`) | la radio |
| `~/.config/cassette-fm/claves.json` | huellas de las claves para escuchar por la nube (`cassette claves`) | la radio |
| `~/.config/cassette-dj/config.toml` | ajustes del servicio DJ | vos |
| `~/.config/cassette-dj/lexico.toml` | pronunciación de nombres propios | vos |
| `~/.config/systemd/user/cassette-*.service` | las unidades de los servicios | los instaladores |
| `~/.local/state/cassette-fm/estado.json` | última emisora, volumen, monitor y agendas de las peticiones | la radio |
| `~/.local/state/cassette-fm/spotify-token.json` | sesión de Spotify (se renueva sola) | `cassette spotify login` |
| `~/.local/state/cassette-fm/reinicio.json` | marcador del último reinicio automático | la radio |
| `~/.cache/cassette-fm/` | duraciones de los temas y `spotify.json` (temas de las playlists) | la radio |
| `~/.local/share/cassette-fm/soloist/` | el binario de Soloist y su sesión | `instalar-spotify.sh` |
| `~/.local/state/cassette-dj/guiones.jsonl` | todo lo que dijo el DJ (no se borra nunca) | el servicio DJ |
| `~/.local/state/cassette-dj/hechos.sqlite` | caché de clima y datos de MusicBrainz | el servicio DJ |
| `~/.local/state/cassette-dj/ensayos/` | registros de `scripts/herramientas/ensayo-dj.py` | el ensayo |
| `~/.local/share/cassette-dj/modelos/` | modelos de voz (Kokoro y `piper/`) | `cassette-dj modelos` |
| `~/.local/share/cassette-dj/ollama/` | modelos del LLM | `instalar-llm.sh` |

Las claves y la API key de Soloist son secretos: no las pongas en capturas, mensajes ni en el repositorio.

## `config.toml` de la radio

```toml
raiz_musica = "~/Música"   # solo para crear estaciones.json la primera vez
puerto = 7710              # la API de control escucha solo en 127.0.0.1
avisos = false             # true: notificación de escritorio con emisora y tema al cambiar
normalizar = true          # parejiza el volumen entre temas (filtro dynaudnorm de mpv)
ajuste_volumen_db = 0      # nivel de las emisoras locales frente a la voz del DJ y Spotify (-30 a 30 dB)
bus_audio = true           # todo el audio sale al sink virtual radio_virtual (ver arquitectura.md)
segundos_hasta_dormir = 60 # sin oyentes tanto tiempo, la radio se duerme sola
```

| Clave | Por defecto | Qué es |
|---|---|---|
| `raiz_musica` | `~/Música` | solo se usa para crear `estaciones.json` la primera vez, con sus subcarpetas |
| `puerto` | `7710` | puerto de la API de control (solo `127.0.0.1`) |
| `avisos` | `false` | notificación de escritorio al cambiar de emisora (el applet ya la muestra) |
| `normalizar` | `true` | parejiza el volumen entre temas |
| `ajuste_volumen_db` | `0` | nivel de las emisoras locales frente a la voz del DJ y a Spotify |
| `bus_audio` | `true` | usa el bus virtual `radio_virtual`. Sin él no hay retransmisión por red ni sueño automático |
| `segundos_hasta_dormir` | `60` | tiempo sin oyentes antes de dormirse |

Los tres niveles (emisoras locales, voz del DJ con `[dj] ganancia_voz_db` y Spotify con `[spotify] ajuste_volumen_db`) se
miden en el bus, antes del volumen del monitor, así que se pueden emparejar sin tocar el volumen de la radio. Con los
valores por defecto la voz y las locales quedan cerca (~-13 dB medios) y Spotify ~-16 dB si su ajuste es 0.
`scripts/herramientas/calibrar-spotify.py` propone el `ajuste_volumen_db` de Spotify.

### `[dj]`

Activa el DJ y lo conecta con su servicio. Todas las claves están en [`dj.md`](dj.md#parámetros-de-dj).

```toml
[dj]
activo = true
url = "http://127.0.0.1:7720"
```

### `[spotify]`

| Clave | Por defecto | Qué es |
|---|---|---|
| `activo` | `true` | `false`: las emisoras de Spotify se ignoran y Soloist no se usa |
| `client_id` | el del autor | el Client ID de la app de desarrollador de Spotify (conviene [la tuya](setup.md#21-tu-propia-app-de-desarrollador-de-spotify)) |
| `puerto_login` | `8888` | puerto del `redirect http://127.0.0.1:<puerto>/callback` del login |
| `ajuste_volumen_db` | `0` | para que Spotify suene tan fuerte como las emisoras locales |
| `nombre_dispositivo` | `cassette-fm` | nombre de Soloist como dispositivo de Spotify |
| `soloist_ws` | `ws://127.0.0.1:9787` | WebSocket local de Soloist |
| `soloist_bin` | `~/.local/share/cassette-fm/soloist/bin/soloist` | dónde está el binario |
| `uris_por_pedido` | `100` | temas que se le mandan a Spotify de una vez |
| `tolerancia_resync_segundos` | `3` | desfase con el reloj que hace re-sintonizar al empezar un tema |
| `timeout_segundos` | `10` | espera máxima por la Web API |

### `[lan]` (otra PC propia)

| Clave | Por defecto | Qué es |
|---|---|---|
| `activo` | `false` | sin esto no se abre ningún puerto |
| `puerto` | `8765` | |
| `escuchar` | `"auto"` | la IP de Tailscale si existe (si no, todas las interfaces) o una IP concreta |
| `max_oyentes` | `4` | |

### `[nube]` (relay en la nube)

| Clave | Por defecto | Qué es |
|---|---|---|
| `activo` | `false` | sin esto no se conecta a nada |
| `url` | — | base del relay: `wss://host[:puerto]` (`ws://` solo contra localhost) |

## `estaciones.json` (las emisoras)

Una lista en el orden en que se rotan:

```json
[
  {"nombre": "Lentos", "fuente": {"carpeta": "~/Música/Lentos"}, "dj": {"idioma": "es", "voz": "daniela"}},
  {"nombre": "Otra", "fuente": {"carpeta": "/media/disco/música/otra"}},
  {"nombre": "Sing", "fuente": {"spotify": "https://open.spotify.com/playlist/<id>"}, "icono": "iconos/sing.png"}
]
```

| Campo | Qué es |
|---|---|
| `nombre` | cómo se llama la emisora (único; se busca sin importar mayúsculas) |
| `fuente` | una carpeta (`{"carpeta": …}`: ruta absoluta o con `~`, en cualquier lugar del disco) **o** una playlist de Spotify (`{"spotify": …}`: link o URI). Una emisora es una u otra, no se mezclan |
| `dj` | (opcional) pisa los ajustes de `[dj]` del `config.toml` solo para esta emisora: `voz`, `idioma`, `personalidad`, `velocidad`, `frecuencia`, `posicion_voz`… (ver [`dj.md`](dj.md)) |
| `icono` | (opcional) imagen PNG, JPG o SVG; ruta absoluta o relativa a `~/.config/cassette-fm/` |

- **La primera vez** el archivo se crea solo con las subcarpetas de `raiz_musica` y los `[dj.estaciones."X"]` que hubiera
  en el `config.toml`. Desde entonces `[dj.estaciones]` del `config.toml` se ignora (avisa una vez en el log).
- `cassette rescan` lo relee. Si quedó mal escrito, la radio sigue con las emisoras que tenía y el comando muestra el error
  con la línea. Si está mal escrito **al arrancar**, el servicio no levanta: el motivo se ve con
  `journalctl --user -u cassette-fm -n 20`.
- El **orden de los temas** de una emisora sale de su nombre y del contenido de su carpeta (o playlist): renombrarla, o
  cambiar lo que tiene, la hace «saltar» a otro punto.
