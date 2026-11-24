# Instalación y configuración

Guía para dejar cassette-fm andando, módulo por módulo y **en orden**. Solo el primer paso es obligatorio: cada uno de
los demás agrega una capacidad y se puede saltear. Si algo no anda, mirá [Problemas frecuentes](#problemas-frecuentes)
al final.

| Paso | Módulo | ¿Obligatorio? | Qué agrega | Qué necesita aparte |
|---|---|---|---|---|
| [1](#1-el-núcleo-radio-comando-y-applet) | **Núcleo**: radio, comando `cassette`, applet, atajos | sí | emisoras de carpetas de música que suenan solas | mpv, PipeWire/PulseAudio |
| [2](#2-emisoras-de-spotify-opcional) | **Spotify** | no | emisoras que son playlists tuyas | cuenta Premium |
| [3](#3-dj-con-voz-opcional) | **DJ** (voz y, si querés, LLM) | no | un locutor que habla entre temas | ~1 GB de disco; Docker para el LLM |
| [4](#4-escuchar-desde-otra-pc-opcional) | **Otra PC** (LAN o Tailscale) | no | la misma radio en una segunda computadora | una segunda PC con Cinnamon |
| [5](#5-escuchar-desde-cualquier-lado-opcional) | **Nube** (relay + web) | no | escuchar desde el celular o el navegador | Docker y una cuenta en un hosting de contenedores |

> **Sobre el entorno.** cassette-fm se hizo y se probó en **Linux Mint (Cinnamon)** con PipeWire. El servicio y el
> comando `cassette` no dependen de Cinnamon, pero el applet, el dial, los atajos y las teclas multimedia sí. En otra
> distribución o escritorio no está probado.

---

## 0. Antes de empezar

**El código.** Copiá la carpeta del proyecto a donde quieras dejarla (por ejemplo `~/Proyectos/cassette-fm`) y
**no la muevas después**: la instalación crea enlaces y un entorno virtual que apuntan a esa ruta. Todos los comandos
de esta guía se corren desde esa carpeta, salvo que diga otra cosa.

**Paquetes del sistema.** En Linux Mint casi todo viene instalado; esto cubre lo que puede faltar:

```bash
sudo apt install python3-venv mpv pulseaudio-utils curl
```

| Hace falta | Para qué | Paso |
|---|---|---|
| Python **3.12** o más nuevo (`python3 --version`) y `python3-venv` | el servicio y la CLI | 1 |
| `mpv` | reproducir la música local | 1 |
| `pactl` (`pulseaudio-utils`; funciona con PipeWire) | el bus de audio virtual `radio_virtual`, que viene activado | 1 |
| `systemd` en modo usuario | los servicios `cassette-fm`, `cassette-dj` y `cassette-soloist` | 1 |
| `gsettings` (viene con Cinnamon) | registrar atajos y habilitar el applet | 1 |
| `curl` | bajar Soloist y esperar a Ollama | 2, 3 |
| Procesador **x86_64** | Spotify Soloist solo se baja para esa arquitectura | 2 |
| `docker` | el servidor de LLM (Ollama) y el relay | 3, 5 |
| `gst-launch-1.0` con `lamemp3enc` (paquetes `gstreamer1.0-tools` y `gstreamer1.0-plugins-good`) | codificar el audio que sale por la red | 4, 5 |
| `notify-send` (`libnotify-bin`) | solo si activás `avisos = true` | — |

Si `~/.local/bin` no está en tu `PATH`, agregalo para que funcione el comando `cassette` (en bash, cerrá y abrí la
sesión; en fish: `fish_add_path ~/.local/bin`).

---

## 1. El núcleo: radio, comando y applet

### 1.1 Poné música en carpetas

Cada emisora es una carpeta de música (mp3, flac, ogg o m4a; se leen también las subcarpetas). La primera vez, el
programa crea las emisoras a partir de **las subcarpetas directas de `~/Música`**:

```
~/Música/
├── Lentos/        → emisora «Lentos»
├── Rock/          → emisora «Rock»
└── Regueton 2000/ → emisora «Regueton 2000»
```

Más adelante podés agregar, quitar o renombrar emisoras, y apuntarlas a carpetas de cualquier lugar del disco (ver
[Emisoras en `uso.md`](uso.md#emisoras)).

### 1.2 Instalá

```bash
scripts/instalar-base.sh
```

Es idempotente: se puede volver a correr cuando quieras (por ejemplo, para actualizar). Son dos componentes, que también se
pueden instalar por separado:

| Script | Qué deja funcionando | Necesita |
|---|---|---|
| `scripts/instalar-radio.sh` | el entorno virtual `.venv` del proyecto, el comando `cassette` en `~/.local/bin` y el servicio de usuario `cassette-fm` (arranca con la sesión), ya levantado y comprobado | nada más |
| `scripts/instalar-escritorio.sh` | los atajos de teclado y el applet del panel de Cinnamon | la radio |

`instalar-base.sh` corre primero uno y después el otro. Si solo querés el servicio y el comando, sin el escritorio (por
ejemplo, en un servidor), alcanza con `scripts/instalar-radio.sh`.

Al terminar, **recargá Cinnamon con `Ctrl+Alt+Esc`** para que aparezca el applet en el panel.

### 1.3 Probalo

```bash
cassette list      # las emisoras y cuántos temas tiene cada una
cassette on        # empezás a escuchar: suena lo que corresponde *ahora*
cassette next      # la emisora siguiente
cassette status    # qué suena y cuántos oyentes hay
```

El servicio arranca con la sesión **dormido**: la radio solo suena si alguien la escucha (`cassette on`, el applet, el
dial o un oyente por la red). Sin oyentes durante 60 segundos se duerme sola. El apagado de verdad es `cassette stop`.

Si algo falla: `journalctl --user -u cassette-fm -e`.

### 1.4 Ajustes básicos (opcionales)

Todo funciona sin tocar nada. Si querés cambiar algo, se escribe en `~/.config/cassette-fm/config.toml`
(que no existe hasta que lo crees) y después `systemctl --user restart cassette-fm`. Las claves están en
[`configuracion.md`](configuracion.md#configtoml-de-la-radio). Las más útiles al empezar:

```toml
raiz_musica = "~/Música"   # de dónde salen las emisoras la primera vez
avisos = false             # true: notificación de escritorio al cambiar de emisora
normalizar = true          # parejiza el volumen entre temas
```

---

## 2. Emisoras de Spotify (opcional)

Una emisora puede ser una playlist de Spotify. Suena con **Spotify Soloist** (el cliente oficial sin ventana, ~45 MB de
RAM), que corre como servicio aparte.

**Requisitos**

- Cuenta de Spotify **Premium**.
- Que la playlist sea **tuya** (creada por vos o colaborativa). Spotify no deja leer los temas de playlists que solo
  seguís (ni las editoriales); para usar una, copiala a una propia.
- Procesador x86_64 y haber hecho el [paso 1](#1-el-núcleo-radio-comando-y-applet).

### 2.1 Tu propia app de desarrollador de Spotify

La radio lee tus playlists por la Web API de Spotify. El `client_id` que trae por defecto es el de la app de
desarrollador del autor, y una app en modo desarrollo admite pocos usuarios, así que **lo normal es crear la tuya**:

1. Entrá a <https://developer.spotify.com/dashboard> y creá una app con la **Web API**.
2. En *Redirect URIs* agregá exactamente `http://127.0.0.1:8888/callback`.
3. Copiá el *Client ID* y ponelo en `~/.config/cassette-fm/config.toml`:

   ```toml
   [spotify]
   client_id = "tu-client-id"
   ```

No hace falta ningún *client secret* (el login usa PKCE).

### 2.2 La API key de Soloist

Soloist pide una API key de desarrollador. Generala en <https://developer.spotify.com/dashboard/soloist>, guardala en
`~/.config/cassette-fm/soloist.key` y protegé el archivo:

```bash
chmod 600 ~/.config/cassette-fm/soloist.key
```

Es personal: no la compartas ni la pegues en ningún lado. (Por eso Soloist va con la clave en su línea de comandos y,
para no exponerla, **no mires los argumentos de ese proceso** con `systemctl status` ni `ps`.)

### 2.3 Instalá Soloist

```bash
scripts/instalar-spotify.sh
```

Un solo script deja Spotify completo. Necesita la radio instalada ([paso 1](#1-el-núcleo-radio-comando-y-applet)) y la API
key del paso anterior. Hace, en orden:

1. Baja Soloist (`scripts/actualizar-soloist.sh`).
2. **Emparejar** (una sola vez): abrí Spotify en el celular, en la misma Wi-Fi que la PC, tocá el ícono de dispositivos y
   elegí «cassette-fm».
3. Instala el servicio `cassette-soloist` y **dirige su audio al bus** de la radio.
4. **Login** (una sola vez): se abre el navegador para darle permiso a cassette-fm sobre tu cuenta.
5. Reinicia la radio y Soloist juntos (la música se corta un instante) y comprueba que la radio responde.

> **Sobre el bus.** La radio mezcla todo en un sink virtual (`radio_virtual`) y lo que oís en esta PC es un monitor de ese
> bus con su propio volumen. El bus viene activado, y el script ya le dirige Soloist; no hay que hacer nada más. Si algún día
> querés la radio sin bus (se pierden el volumen unificado, la retransmisión por red y el sueño automático por falta de
> oyentes), `scripts/bus-audio.sh quitar` lo desactiva y `scripts/bus-audio.sh activar` lo vuelve a poner. Ver
> [arquitectura](arquitectura.md#el-bus-de-audio).

### 2.4 Probalo

```bash
cassette spotify estado                                   # tu cuenta y los temas de cada emisora de Spotify
cassette nueva "Synthwave F.M." <link de tu playlist>     # crea la emisora y la sintoniza
```

El uso de las emisoras de Spotify (peticiones por la cola, qué hace si Spotify tarda) está en [`uso.md`](uso.md#spotify).

> **El build de Soloist vence cada 90 días.** `cassette spotify estado` avisa cuando faltan menos de 14. Se renueva con
> `scripts/actualizar-soloist.sh`.

---

## 3. DJ con voz (opcional)

El DJ es un locutor que habla entre temas: presenta lo que viene, dice la hora o el clima de tu ciudad, o un dato
verificado del artista. Lo hace un **servicio aparte** (`cassette-dj`) que escribe y sintetiza las frases; la radio solo
necesita su dirección, así que puede correr en esta PC o en otra. Las voces corren en CPU con Kokoro y Piper.

### 3.1 Instalá el servicio de voz

```bash
scripts/instalar-dj.sh
```

Un solo script deja el servicio DJ completo: instala el extra `[dj,piper]` y el comando `cassette-dj`, **baja los modelos de
voz de Kokoro** (~350 MB, una sola vez) y crea y arranca el servicio de usuario `cassette-dj`, comprobando que responde. No
necesita la radio (por eso puede vivir en otra máquina: copiá el proyecto allá y corré el mismo script).

Con eso ya habla en **inglés** (la voz por defecto es `af_heart`, de Kokoro). Para **español rioplatense** hace falta una voz
de Piper; la que mejor anduvo es `es_AR-daniela-high`. Se baja con la misma instalación (se puede repetir la opción):

```bash
scripts/instalar-dj.sh --voz-piper es_AR-daniela-high
```

(Las voces de Piper están en [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices).)

### 3.2 Poneles nombre a las voces (alias)

En `~/.config/cassette-dj/config.toml` (el del servicio DJ) dale un alias corto a cada voz que quieras usar; después se
usa el alias en las emisoras:

```toml
[voces]
daniela = "piper:es_AR-daniela-high"   # una voz de Piper: «piper:» + el nombre del modelo
puck = "am_puck"                       # una voz de Kokoro
```

`systemctl --user restart cassette-dj` para que los lea. `cassette-dj voces` lista los alias y todo lo que se puede usar.

### 3.3 Conectá la radio con el DJ

En `~/.config/cassette-fm/config.toml`, **las dos cosas** (sin `url` no intenta conectarse a nada):

```toml
[dj]
activo = true
url = "http://127.0.0.1:7720"
```

Reiniciá: `systemctl --user restart cassette-fm`. Después, en `~/.config/cassette-fm/estaciones.json`, elegí la voz y el
idioma de cada emisora (`cassette rescan` aplica el cambio sin cortar la música):

```json
{"nombre": "Lentos", "fuente": {"carpeta": "~/Música/Lentos"}, "dj": {"idioma": "es", "voz": "daniela"}}
```

### 3.4 Probalo

```bash
cassette dj estado          # tiene que decir «servicio DJ: ok»
cassette dj pedir --en 30   # le pide una intervención real para el primer tema que arranque en ≥ 30 s
```

Sintonizá una emisora y escuchá. Si lo dejás solo, habla cada 2–3 temas. Si las emisoras llevan un alias que no existe,
las intervenciones fallan y la música sigue sin voz (queda en `cassette-dj guiones` y en el log del servicio).

### 3.5 Datos reales en las frases (recomendado)

Con el clima de tu ciudad y datos de MusicBrainz el DJ dice cosas verificables. **MusicBrainz pide un contacto en el
`User-Agent`**; sin él no se consulta. En `~/.config/cassette-dj/config.toml`:

```toml
contacto = "tu@mail"       # no se guarda en ningún otro lado
latitud = -34.61           # por defecto, Buenos Aires
longitud = -58.38
zona_horaria = "America/Argentina/Buenos_Aires"
```

`systemctl --user restart cassette-dj`. Verificá con `cassette-dj hechos` (el clima de ahora) y
`cassette-dj hechos --artista "a-ha" --titulo "Take On Me"` (tiene que dar 1984, Noruega y grupo desde 1983).

### 3.6 Un LLM local para redactar (opcional)

Por defecto el DJ redacta con **plantillas**. Con un LLM local (Ollama) las frases salen más variadas, usando los hechos
verificados y el resumen de Wikipedia del artista. Necesita Docker, unos 3 GB de descarga y bastante RAM.

```bash
scripts/instalar-llm.sh        # contenedor cassette-ollama (solo en 127.0.0.1:11434) y descarga del modelo
cassette-dj llm estado         # URL, modelo, si responde y si el modelo está bajado
cassette dj modo llm           # pasa a LLM (vuelve a plantillas al reiniciar el servicio DJ)
```

Con el LLM conviene `margen_minutos = 3` o más en `[dj]`, para que le dé tiempo a escribir. Todo lo demás del DJ
(frecuencia, posición de la voz, volumen, modos, ensayos) está en [`dj.md`](dj.md).

---

## 4. Escuchar desde otra PC (opcional)

Una segunda PC propia escucha **la misma transmisión** con el mismo applet, sin correr nada del backend (ni Soloist, ni
Docker, ni el DJ). Lo que suena allá es lo del bus `radio_virtual` de esta PC, con 1–3 s de retraso; cambiar de emisora
desde cualquiera de las dos la cambia para las dos, y cada PC tiene su volumen y su escucha. Funciona por la LAN o por
[Tailscale](https://tailscale.com) (que además cifra el tráfico).

### 4.1 En la PC principal

Hace falta el bus de audio (`bus_audio = true`, que viene por defecto) y `gst-launch-1.0` (ver [paso 0](#0-antes-de-empezar)).

```toml
# ~/.config/cassette-fm/config.toml
[lan]
activo = true            # apagado por defecto: sin esto no se abre ningún puerto
# puerto = 8765
# escuchar = "auto"      # la IP de Tailscale si existe (si no, todas las interfaces) o una IP concreta
# max_oyentes = 4
```

```bash
systemctl --user restart cassette-fm
cassette lan               # muestra la dirección (la de Tailscale si hay, que es fija) y la clave de oyente
```

`cassette lan regenerar` cambia la clave. Va por HTTP sin cifrar: por Tailscale ya viaja cifrado, por la LAN sirve
para una red de confianza.

### 4.2 En la otra PC

1. Instalá `python3` y `mpv`.
2. Copiá o enlazá la carpeta `applet/cassette-fm@cassette-fm` a `~/.local/share/cinnamon/applets/` y habilitá el applet
   en el panel (clic derecho en el panel → *Applets*).
3. En los ajustes del applet prendé **Modo remoto** y completá **Dirección de la radio remota**
   (`http://100.x.y.z:8765`) y **Clave de oyente**.
4. Si no se ve, reiniciá Cinnamon (`Alt+F2`, `r`).

El applet remoto se ve igual que el local (menú, dial, logos), salvo que no ofrece editar emisoras. Si algo falla, el
tooltip lo dice (clave rechazada, no alcanzo a la radio, la radio principal está apagada).

---

## 5. Escuchar desde cualquier lado (opcional)

Para escuchar y manejar la radio desde el teléfono con datos, una tablet o una compu cualquiera, **sin instalar nada**
en ellos: esta PC se conecta **hacia afuera** a un *relay* en la nube (no abre puertos ni expone su IP) y el relay
atiende a los oyentes con una web en forma de dial. En Android se puede instalar como app.

Son dos piezas: el **puente** (ya viene en la radio, se activa con `[nube]`) y el **relay** (un contenedor Docker, en
[`relay/`](../relay/README.md)).

El orden:

1. **Elegí una clave maestra** (de 8 caracteres o más): es la que usás vos desde cualquier dispositivo y funciona aunque
   esta PC esté apagada. Es `MASTER_PASSWORD` del relay.
2. **Tomá la clave de esta PC**: el contenido de `~/.config/cassette-fm/nube.token` (también la muestra
   `cassette nube`). Es `INGEST_TOKEN` del relay.
3. **Levantá el relay.** Primero probalo en casa y después publicalo en un hosting gratuito (Render, por ejemplo). Los
   comandos exactos (build, Docker Hub, Render) están en [`relay/README.md`](../relay/README.md).
4. **Activá el puente** en `~/.config/cassette-fm/config.toml` y reiniciá:

   ```toml
   [nube]
   activo = true                        # apagado por defecto: sin esto no se conecta a nada
   url = "wss://tu-servicio.onrender.com"   # ws:// solo contra localhost
   ```

   ```bash
   systemctl --user restart cassette-fm
   cassette nube          # dice si conectó y qué calidades de audio se están subiendo
   ```

5. **Abrí la web** (`https://tu-servicio.onrender.com/`) e ingresá con la clave maestra.

### Claves para otras personas

La maestra es la única clave en el relay. Las demás se crean desde esta PC, sin tocar el relay:

```bash
cassette claves nueva Mamá              # solo escuchar; muestra la clave UNA sola vez
cassette claves nueva Papá --completa   # escuchar y cambiar de emisora
cassette claves                         # las lista
cassette claves borrar Mamá             # quien la usaba queda afuera en segundos
```

Se guardan en `~/.config/cassette-fm/claves.json`, solo con su huella; el servicio se las pasa al relay solo.

> El plan gratuito de Render duerme el relay tras 15 minutos sin tráfico (no pasa con la PC prendida, porque el puente
> manda un latido) y corta el audio a los 100 minutos (la web lo reabre sola). Los detalles están en
> [`relay/README.md`](../relay/README.md#qué-esperar-del-plan-gratis).

---

## Mantenimiento

| Quiero… | Comando |
|---|---|
| Actualizar el código | traé la versión nueva y volvé a correr el instalador de cada componente que uses (`scripts/instalar-radio.sh`, `instalar-dj.sh`, `instalar-spotify.sh`); reinician sus servicios y la música se corta un instante |
| Renovar Soloist (vence a los 90 días) | `scripts/actualizar-soloist.sh` |
| Quitar o volver a poner el bus de audio | `scripts/bus-audio.sh quitar` / `activar` |
| Apagar todo y liberar memoria | `cassette stop` (radio, Soloist, DJ y Ollama); `cassette start` lo levanta |
| Reiniciar la radio | `systemctl --user restart cassette-fm` |
| Reiniciar el DJ | `systemctl --user restart cassette-dj` |
| Aplicar cambios de `estaciones.json` sin cortar la música | `cassette rescan` |
| Ver los logs | `journalctl --user -u cassette-fm -f` (también `-u cassette-dj`) |

## Problemas frecuentes

- **`cassette: command not found`**: falta `~/.local/bin` en el `PATH` (ver [paso 0](#0-antes-de-empezar)).
- **No aparece el applet**: recargá Cinnamon con `Ctrl+Alt+Esc`. Si hay errores: `Alt+F2`, escribí `lg`, pestaña
  *Errors* (Looking Glass).
- **El servicio no arranca**: `journalctl --user -u cassette-fm -n 20`. Si `estaciones.json` está mal escrito, ahí se ve
  el motivo y la línea.
- **Suena la radio pero no el DJ**: `cassette dj estado` (¿`servicio DJ: ok`?) y `journalctl --user -u cassette-dj -e`.
- **Spotify no suena**: `cassette spotify estado` (¿sesión iniciada? ¿build de Soloist vencido?) y que no tengas Spotify
  abierto reproduciendo en otro dispositivo (Premium toca en uno solo).
- **No sale sonido y hay `bus_audio`**: `pactl list short sinks | grep radio_virtual` tiene que mostrar el bus. Sin
  `pactl` el servicio arranca igual pero sin bus; en ese caso poné `bus_audio = false` en `config.toml`.
- **Tocaste el applet y no cambia**: `ReloadXlet` recarga `applet.js` pero no `logic.js`; para ese hace falta reiniciar
  Cinnamon.

## Qué hace cada script

Los scripts de [`scripts/`](../scripts/) se corren desde la raíz del proyecto. **Cada instalador deja un componente
completo**: instala, configura, arranca y comprueba lo suyo, y avisa si le falta algo de lo que depende. Son idempotentes.

| Componente | Script | Necesita | Deja funcionando |
|---|---|---|---|
| Radio | `scripts/instalar-radio.sh` | nada más | el servicio `cassette-fm` y el comando `cassette` |
| Escritorio | `scripts/instalar-escritorio.sh` | la radio | atajos de teclado y applet de Cinnamon |
| *Lo básico* | `scripts/instalar-base.sh` | nada más | la radio y el escritorio, uno tras otro |
| Spotify | `scripts/instalar-spotify.sh` | la radio y la API key de Soloist | el servicio `cassette-soloist` (con su audio en el bus), el emparejamiento y el login |
| DJ | `scripts/instalar-dj.sh` | nada más (no necesita la radio) | el servicio `cassette-dj` con sus modelos de voz |
| LLM del DJ | `scripts/instalar-llm.sh` | Docker (no necesita el DJ para instalarse) | el contenedor `cassette-ollama` con el modelo descargado |

Para unir el DJ con una radio no hay script: es configuración (`[dj] activo` y `url`, [paso 3.3](#33-conectá-la-radio-con-el-dj)).

**Mantenimiento y ajustes:**

| Script | Qué hace |
|---|---|
| `scripts/actualizar-soloist.sh` | renueva el build de Soloist (vence a los 90 días) y reinicia su servicio |
| `scripts/bus-audio.sh activar\|quitar` | prende o apaga el bus de audio de la radio, con el enrutado de Soloist si está instalado |

**Herramientas** (en [`scripts/herramientas/`](../scripts/herramientas/); no instalan nada, no hacen falta para usar la radio):

| Script | Qué hace |
|---|---|
| `calibrar-spotify.py` | propone el `ajuste_volumen_db` para que Spotify suene como las emisoras locales |
| `ensayo-dj.py` | ensaya el DJ en todas las emisoras (ver [`dj.md`](dj.md#ensayar-el-dj)) |
| `capturar-cola-soloist.py` | diagnóstico de la cola de Spotify |
| `renderizar-icono.py` | genera los íconos de la marca |

`scripts/lib/comun.sh` no se ejecuta: son las funciones que comparten los instaladores.
