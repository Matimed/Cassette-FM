# cassette-fm

Convierte las carpetas de `~/Música` en **radios continuas**: cada subcarpeta es una estación que "suena" todo el
tiempo en orden aleatorio, y al sintonizarla se entra con el tema ya empezado. Un servicio local (Python + mpv)
lleva el reloj de cada estación y se controla con el comando `cassette`.

Diseño: [`docs/superpowers/specs/2026-11-13-cassette-fm-design.md`](docs/superpowers/specs/2026-11-13-cassette-fm-design.md).

## Instalación

Requiere Python 3.12 y mpv. Un solo comando instala el servicio, el comando `cassette`, los atajos de
teclado y el applet del panel de Cinnamon:

```bash
scripts/instalar-todo.sh
```

Después recargá Cinnamon con `Ctrl+Alt+Esc` para ver el applet. Se puede correr las veces que haga falta.
El servicio arranca con la sesión **en silencio**: solo suena con `cassette on` (o con el applet).

Si solo querés el servicio y la CLI, sin el escritorio: `scripts/instalar.sh`.

## Uso

| Comando | Qué hace |
|---|---|
| `cassette on` / `off` / `toggle` | enciende, apaga o alterna (al encender suena lo que corresponde *ahora*) |
| `cassette next` / `prev` | estación siguiente o anterior (alfabético, con vuelta) |
| `cassette tune <nombre>` | sintoniza por nombre o por el comienzo (`cassette tune reg`) |
| `cassette status` | qué suena |
| `cassette list` | estaciones y cantidad de temas |
| `cassette vol 70` / `+5` / `-5` | volumen; en 0 la radio se apaga (como un mute) y subirlo la enciende |
| `cassette rescan` | vuelve a leer `~/Música` |
| `cassette serve` | levanta el servicio a mano (sin systemd) |

## Applet de Cinnamon

Un ícono en el panel con el nombre de la estación (vacío si está apagada). Rueda del mouse: hacia arriba pasa
a la estación siguiente y hacia abajo a la anterior. Clic izquierdo: enciende o apaga. Clic derecho: lista de
estaciones para elegir una. El tooltip muestra estación, tema y volumen; si el servicio no está, dice que no
responde. En los ajustes del applet se cambia el puerto y si se muestra el nombre.

Si algo falla: `Alt+F2`, escribir `lg`, pestaña *Errors* (Looking Glass), y `journalctl --user -u cassette-fm -e`.

## Atajos de teclado (Cinnamon)

`cassette atajos` (ya lo hace `instalar-todo.sh`) registra estas teclas (no pisa las que ya uses ni las que cambies a mano):

| Tecla | Acción |
|---|---|
| `Super+Alt+→` / `Super+Alt+←` | estación siguiente / anterior |
| `Super+Alt+↑` / `Super+Alt+↓` | volumen +10 / −10 (en 0 se apaga; subir lo enciende) |

## Configuración

`~/.config/cassette-fm/config.toml` (todas las claves son opcionales):

```toml
raiz_musica = "~/Música"   # cada subcarpeta es una estación
puerto = 7710              # la API escucha solo en 127.0.0.1
avisos = true              # notificación de escritorio con estación y tema
normalizar = true          # parejiza el volumen entre temas (filtro dynaudnorm de mpv)
```

El estado (última estación y volumen) se guarda en `~/.local/state/cassette-fm/estado.json`.

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Logs del servicio: `journalctl --user -u cassette-fm -f`.
