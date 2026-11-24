# cassette-fm

<img src="branding/casete.png" alt="" width="96" align="right">

**Tu música, como una radio de verdad.** cassette-fm convierte carpetas de música (y playlists de Spotify) en
**emisoras continuas**: cada una «suena» todo el tiempo, en orden aleatorio, y al sintonizarla **entrás con el tema ya
empezado**, como en las radios de GTA que inspiraron la idea. Cambiás de emisora con la rueda del mouse, un atajo, un
dial en pantalla o los botones de un parlante Bluetooth.

Es un proyecto personal para Linux Mint (Cinnamon): liviano, hecho para dejarlo andando todo el día y para que sea
divertido de usar.

## Qué tiene

- **Radios que nunca paran.** Cada emisora tiene su propio reloj virtual: sintonizás y suena lo que *estaría sonando*
  ahora. Las que no escuchás no gastan nada, y si nadie escucha ninguna, la radio entera se duerme sola.
- **Música local y Spotify.** Una emisora es una carpeta de tu disco o una playlist tuya de Spotify (Premium); las dos se
  comportan igual. Lo que agregás a la cola de Spotify suena como una **petición especial**.
- **Un DJ por emisora.** Un locutor con voz propia que habla entre temas, con la música bajada: presenta lo que viene, dice
  la hora, el clima o un dato verificado del artista. Las frases salen de plantillas o de un LLM local, y nunca inventa
  datos. Es opcional.
- **Manejo de escritorio.** Un applet en el panel, un **dial** de logos estilo GTA (`Super+Alt+Espacio`), atajos de
  teclado y teclas multimedia (los botones de un parlante Bluetooth cambian de emisora).
- **Escuchala donde quieras.** En una segunda PC con el mismo applet (por la red de casa o por Tailscale) o desde el
  teléfono, una tablet o cualquier navegador, con una web en forma de dial que se instala como app en Android. Una sola
  transmisión: cambiás de emisora en un lado y cambia en todos.

## Cómo funciona, en una mirada

Un servicio local en Python (`cassette-fm`) calcula qué suena en cada emisora a partir de un reloj, reproduce con mpv (o
con Spotify Soloist) y mezcla todo en un bus de audio virtual. De ese bus sale lo que oís en esta PC y lo que se
retransmite por la red. El DJ es un servicio aparte que puede correr en otra máquina. Todo se controla con el comando
`cassette`, el applet o la web.

Las decisiones de fondo (por qué un reloj virtual, por qué Soloist, por qué un bus de audio) están en
[`docs/arquitectura.md`](docs/arquitectura.md).

## Empezar

Necesitás Python 3.12, mpv y un Linux con Cinnamon. Con las carpetas de música en `~/Música` (una subcarpeta por emisora):

```bash
scripts/instalar-base.sh      # la radio (servicio y comando `cassette`) y el escritorio (atajos y applet)
# recargá Cinnamon con Ctrl+Alt+Esc para ver el applet
cassette on                  # y a escuchar
```

Eso alcanza para tener la radio andando. Spotify, el DJ, la segunda PC y la nube se suman después, cada uno por su lado:
la guía paso a paso está en [`docs/setup.md`](docs/setup.md).

Lo de todos los días, en una tabla corta:

| Quiero… | Hago… |
|---|---|
| escuchar / dejar de escuchar | `cassette on` / `cassette mute`, o clic en el applet |
| cambiar de emisora | `cassette next` / `prev` / `tune <nombre>`, la rueda del applet, `Super+Alt+←/→` o el dial |
| ver qué suena | `cassette status` |
| subir o bajar el volumen | `cassette vol +5` / `-5`, o `Super+Alt+↑/↓` |
| apagar todo y liberar memoria | `cassette stop` (`cassette start` lo levanta) |

## Documentación

| Documento | Para qué sirve |
|---|---|
| [`docs/setup.md`](docs/setup.md) | **Instalar y configurar** cada módulo, en orden: núcleo, Spotify, DJ, otra PC y nube. Incluye problemas frecuentes y qué hace cada script |
| [`docs/uso.md`](docs/uso.md) | **Usarlo todos los días**: comandos, applet, dial, atajos, manejo de emisoras, Spotify y peticiones |
| [`docs/dj.md`](docs/dj.md) | **El DJ**: cómo funciona, parámetros, modos (plantillas, LLM), voces, hechos reales y contrato del servicio |
| [`docs/configuracion.md`](docs/configuracion.md) | **Referencia**: dónde vive cada archivo y cada clave de `config.toml` y `estaciones.json` |
| [`docs/arquitectura.md`](docs/arquitectura.md) | **Por qué está hecho así**: componentes, puertos y decisiones técnicas |
| [`relay/README.md`](relay/README.md) | **El relay en la nube**: levantarlo, publicarlo y su API |
| [`docs/project-context.md`](docs/project-context.md) | Estado del proyecto y bitácora, para quien retoma el trabajo |

Cada pieza tiene además su documento de diseño en [`docs/superpowers/specs/`](docs/superpowers/specs/) y su plan en
[`docs/superpowers/plans/`](docs/superpowers/plans/).

## Estado

Todo lo de la lista de arriba está implementado: radio local, applet, dial y atajos, DJ con plantillas y con LLM, Spotify
con peticiones, radio por oyentes, escucha desde otra PC y desde la nube. Lo pendiente se lleva como tareas con Beans
dentro del repositorio (`.beans/`; `beans list`).

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Los logs del servicio: `journalctl --user -u cassette-fm -f`.

## Créditos

El casete de la marca es de Flaticon, cuya licencia gratuita pide dar crédito al autor (ver
[`branding/README.md`](branding/README.md)). Las voces del DJ son Kokoro y Piper; el reproductor de Spotify, Spotify
Soloist; los datos, de open-meteo, MusicBrainz y Wikipedia.
