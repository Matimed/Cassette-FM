# cassette-fm

Convierte las carpetas de `~/Música` en **radios continuas**: cada subcarpeta es una estación que "suena" todo el
tiempo en orden aleatorio, y al sintonizarla se entra con el tema ya empezado. Un servicio local (Python + mpv)
lleva el reloj de cada estación y se controla con el comando `cassette`.

Diseño: [`docs/superpowers/specs/2026-11-13-cassette-fm-design.md`](docs/superpowers/specs/2026-11-13-cassette-fm-design.md).

## Instalación

Requiere Python 3.12 y mpv.

```bash
scripts/instalar.sh
```

Crea `.venv`, deja `cassette` en `~/.local/bin` e instala y arranca el servicio de usuario `cassette-fm`.
El servicio arranca con la sesión **en silencio**: solo suena con `cassette on`.

## Uso

| Comando | Qué hace |
|---|---|
| `cassette on` / `off` / `toggle` | enciende, apaga o alterna (al encender suena lo que corresponde *ahora*) |
| `cassette next` / `prev` | estación siguiente o anterior (alfabético, con vuelta) |
| `cassette tune <nombre>` | sintoniza por nombre o por el comienzo (`cassette tune reg`) |
| `cassette status` | qué suena |
| `cassette list` | estaciones y cantidad de temas |
| `cassette vol 70` / `+5` / `-5` | volumen |
| `cassette rescan` | vuelve a leer `~/Música` |
| `cassette serve` | levanta el servicio a mano (sin systemd) |

## Configuración

`~/.config/cassette-fm/config.toml` (todas las claves son opcionales):

```toml
raiz_musica = "~/Música"   # cada subcarpeta es una estación
puerto = 7710              # la API escucha solo en 127.0.0.1
avisos = true              # notificación de escritorio con estación y tema
```

El estado (última estación y volumen) se guarda en `~/.local/state/cassette-fm/estado.json`.

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Logs del servicio: `journalctl --user -u cassette-fm -f`.
