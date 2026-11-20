# Relay en la nube de cassette-fm

Punto de encuentro entre la radio de casa y quien la escucha desde cualquier red. La PC se conecta **hacia afuera** a
este relay (el puente, `[nube]` en `config.toml`) y el relay atiende a los oyentes: les reparte el audio, les muestra
el estado y le pasa a la PC las órdenes (sintonizar, siguiente, anterior). La PC sube cada calidad una sola vez, y
solo mientras alguien la escucha.

Diseño: [`docs/superpowers/specs/2026-11-19-relay-nube-design.md`](../docs/superpowers/specs/2026-11-19-relay-nube-design.md).

## Variables

| Variable | Qué es |
|---|---|
| `INGEST_TOKEN` | La clave de la PC: el contenido de `~/.config/cassette-fm/nube.token` (la muestra `cassette nube`). |
| `MASTER_PASSWORD` | La clave maestra: siempre escucha y maneja la radio, y funciona aunque la PC esté apagada (al menos 8 caracteres). Cambiarla cierra todas las sesiones. Es la única clave de oyentes que queda en el entorno: las demás se crean desde la PC (ver «Claves»). |
| `PORT` | Puerto donde escucha (Render la pone sola). Por defecto 8080. |

Si `cassette nube regenerar` cambia la clave de la PC, hay que actualizar `INGEST_TOKEN` en el relay.

## Probarlo en esta PC

Los comandos son de fish (la shell de esta PC). La clave se toma del archivo y va por el entorno, así no queda en la
línea de comandos de ningún proceso.

Con Docker:

```fish
docker build -t cassette-relay relay/
begin
    set -lx INGEST_TOKEN (cat ~/.config/cassette-fm/nube.token)
    set -lx MASTER_PASSWORD 'una-clave-maestra'
    docker run --rm -p 8080:8080 -e INGEST_TOKEN -e MASTER_PASSWORD cassette-relay
end
```

Sin Docker (con el venv del proyecto):

```fish
begin
    set -lx INGEST_TOKEN (cat ~/.config/cassette-fm/nube.token)
    set -lx MASTER_PASSWORD 'una-clave-maestra'
    cd relay; ../.venv/bin/python -m cassette_relay
end
```

Después, en `~/.config/cassette-fm/config.toml`:

```toml
[nube]
activo = true
url = "ws://127.0.0.1:8080"
```

`systemctl --user restart cassette-fm`. `cassette nube` dice si conectó. La página de prueba está en
`http://127.0.0.1:8080/`; desde el teléfono en el wifi de casa, `http://<IP de esta PC>:8080/`.

## Publicar la imagen en Docker Hub

La imagen no lleva ninguna clave, así que puede ser pública.

```fish
docker login
docker build -t <usuario>/cassette-relay:latest relay/
docker push <usuario>/cassette-relay:latest
```

## Crear el servicio en Render (plan gratis)

1. *New* → *Web Service* → *Existing Image*, con `docker.io/<usuario>/cassette-relay:latest`.
2. *Instance type*: **Free**.
3. *Environment*: `INGEST_TOKEN` y `MASTER_PASSWORD` (no hace falta `PORT`).
4. *Advanced* → *Health Check Path*: `/salud`.
5. Crear. La URL queda como `https://<servicio>.onrender.com`.

Después de cada `docker push`: *Manual Deploy* → *Deploy latest reference*.

En la PC:

```toml
[nube]
activo = true
url = "wss://<servicio>.onrender.com"
```

`systemctl --user restart cassette-fm` y `cassette nube` para ver que conectó. Desde el teléfono:
`https://<servicio>.onrender.com/`.

## Qué esperar del plan gratis

- **Se duerme sin la PC.** Render apaga el servicio tras 15 min sin tráfico entrante. Con la PC prendida no pasa,
  porque el puente manda un `latido` cada 2 min. Con la PC apagada se duerme, y el primero que abre la página lo
  despierta en alrededor de un minuto y ve "fuera de línea".
- **Corte a los 100 min.** Render corta un pedido HTTP a los 100 min, y el audio es un pedido HTTP. La página reabre
  el audio sola, con un hueco de 1 o 2 segundos.
- **Todo en memoria.** Si Render reinicia el relay, la PC se reconecta sola y vuelve a mandar el estado y los logos.
- **750 horas por mes**, justo para un servicio prendido todo el mes.

## Instalarla como app (Android)

Abrí `https://<servicio>.onrender.com/` en Chrome → menú ⋮ → *Instalar app*. Queda con su ícono, sin la barra de Chrome y con
el splash oscuro; la reproducción sigue con la pantalla apagada y se maneja desde las notificaciones. Si antes habías creado un
acceso directo ("Agregar a la pantalla principal" sin manifest), borralo y volvé a instalar.

## Claves

La maestra (`MASTER_PASSWORD`) es la única en el entorno. Las otras se manejan desde la PC, sin tocar el relay:

```fish
cassette claves nueva Mamá              # solo escuchar; muestra la clave una sola vez
cassette claves nueva Papá --completa   # escuchar y cambiar de emisora
cassette claves                         # lista (nombre, permiso, fecha)
cassette claves borrar Mamá             # quien la usaba queda afuera en segundos
```

La PC guarda solo la huella de cada clave (`~/.config/cassette-fm/claves.json`) y le manda al relay la lista (sin
nombres) por el puente, al conectar y cada vez que cambia. El relay la tiene en memoria. Por eso:

- Una clave recién creada entra a los pocos segundos; borrarla corta su audio en el acto.
- Si la PC está apagada, el relay conserva la última lista, pero solo la maestra puede entrar con clave; las sesiones
  ya abiertas siguen.
- Si el relay se reinicia (Render lo duerme), hasta que la PC reconecte y mande la lista valen las sesiones abiertas
  con el permiso que tenían, y entra solo la maestra con clave.

## API de los oyentes

Todas las rutas de `/api/` piden la cookie de sesión (la pone `POST /api/entrar`, dura 180 días) o
`Authorization: Bearer <clave>` (la maestra o una clave de la PC). Después de 5 claves equivocadas en un minuto,
probar una clave queda bloqueado un minuto (también con el encabezado); quien ya entró con la cookie sigue.
Las claves de solo escucha reciben **403** al sintonizar, ir al siguiente o al anterior.

| Ruta | Qué hace |
|---|---|
| `POST /api/entrar` `{"clave": "…"}` | Pone la cookie de sesión. |
| `POST /api/salir` | Borra la cookie. |
| `GET /api/estado` | `{"en_linea", "visto_hace", "calidades", "radio", "permiso"}` (`radio`: lo último que mandó la PC; `permiso`: `escucha` o `completa`). |
| `POST /api/sintonizar` `{"estacion": "…"}` | Cambia de emisora (también `/api/siguiente` y `/api/anterior`). |
| `GET /api/escuchar?calidad=64` | El MP3 en vivo (64, 96 o 160 kbps). |
| `GET /api/icono/<emisora>?v=<versión>` | El logo de una emisora. |
| `GET /salud` | `ok` (sin clave). |

Fuera de la página, mpv puede escuchar con la clave en un encabezado (queda en su línea de comandos, así que solo en
un equipo propio):

```fish
mpv --loop=inf --http-header-fields="Authorization: Bearer <clave>" "https://<servicio>.onrender.com/api/escuchar?calidad=96"
```

VLC no puede mandar ese encabezado: desde VLC, mejor la página.

## Tests

Corren con el pytest del repo (`.venv/bin/pytest relay/tests`). Incluyen pruebas de punta a punta con el puente real
de la PC.
