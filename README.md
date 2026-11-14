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

## DJ (en desarrollo)

La Etapa 3 agrega un DJ que habla entre temas. Hoy está la **parte 1**: la radio sabe reproducir un clip de voz en
un hueco reservado de la agenda de una estación, con la música bajada, y entrar a mitad de frase si sintonizás con
la intervención en curso. Todavía no hay servicio que genere las frases: se prueba con clips fijos.

**Viene apagado.** Para activarlo, en `~/.config/cassette-fm/config.toml`:

```toml
[dj]
activo = true
```

y `systemctl --user restart cassette-fm`. Con `activo = false` no se crea nada (ni el segundo mpv).

| Comando | Qué hace |
|---|---|
| `cassette dj probar` | registra un clip de tonos en el próximo hueco de la estación sintonizada (a ≥ 20 s) |
| `cassette dj probar --audio clip.wav --en 45` | usa tu propio clip (≤ la duración máxima) y una antelación de 45 s |
| `cassette dj estado` | qué tiene programado el DJ, si está hablando y el desfase entre mpv y el reloj |

Parámetros de la sección `[dj]` (todos opcionales; también se pueden pisar por estación con
`[dj.estaciones."Nombre"]`):

| Clave | Por defecto | Qué es |
|---|---|---|
| `duracion_maxima_segundos` | 15 | tope de duración de la voz |
| `retraso_voz_segundos` | 1 | cuánto después del comienzo del tema entra la voz |
| `nivel_musica_con_voz` | 0.35 | volumen de la música mientras habla (fracción del tuyo) |
| `rampa_bajada_segundos` / `rampa_subida_segundos` | 0.4 / 1 | tiempo de bajar y de volver a subir la música |
| `minimo_restante_segundos` | 1.5 | si queda menos de esto de la frase, no se reproduce |
| `tolerancia_desfase_segundos` | 60 | cuánto puede apartarse el inicio real del tema del previsto |
| `desfase_aviso_segundos` | 5 | desfase a partir del cual se avisa en el log |
| `margen_seguridad_voz_segundos` | 2 | espera extra del temporizador que restaura la música |

**Cómo probarlo con audio real:** sintonizá una estación, corré `cassette dj probar --en 20` y comprobá que
(a) la voz entra ~1 s después de que arranca el tema siguiente, con la música bajada; (b) si cambiás de estación
y volvés con la voz todavía sonando, retoma la frase en el punto que corresponde; (c) bajar el volumen a 0 la corta;
(d) `cassette dj estado` informa el desfase.

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
