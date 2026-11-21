# Radio por oyentes: la radio suena si alguien la escucha

Tarea: CASSETTE-FM-ta67 (hoy "apagar la radio sola sin oyentes y despertarla al volver uno"; este diseño la amplía).
Estado: diseño aprobado en la conversación del 2026-11-20, pendiente de plan.

## Intención

Hoy "encendida/apagada" es un interruptor que manejan sobre todo las interfaces de esta PC (clic del applet, "Apagar", `cassette off`,
`/apagar`, y varios comandos que además prenden el monitor local). Resultado: esta PC es un oyente con más privilegios que los demás
(la notebook, el teléfono, la web) y la radio puede quedar reproduciendo música (y Spotify gastando recursos) para nadie.

El cambio de concepto: **la radio es un servicio que cualquier oyente despierta y que se duerme sola cuando no tiene oyentes.**
El único apagado definitivo es `systemctl --user stop`. La forma natural de apagar la radio es dejar de escuchar en todos lados.
Todas las interfaces siguen las mismas reglas, sin privilegios especiales para la PC principal.

## Metas

- La radio suena solo si hay al menos un oyente; sin oyentes durante la gracia, se duerme (se detiene la reproducción, incluido Spotify).
- Un oyente nuevo (stream abierto, o alguien que elige emisora con cero oyentes) la despierta.
- Reglas unificadas de "oyente" para todas las interfaces (applet local, applet remoto, receptor LAN, nube/web, MPRIS, CLI).
- Quitar de las interfaces el apagado como acción propia; `cassette stop` hace el `systemctl`.

## No metas

- No cambia el audio, el DJ, las emisoras ni el relay (la web del relay cumple la regla de cliente de abajo, pero su código no se toca acá).
- No hay permisos por usuario: lo administrativo (crear o borrar emisoras, claves, `rescan`) sigue siendo de la API local en loopback y no es un tema de oyentes.
- Sin bus de audio (`bus_audio = false`) no se pueden contar oyentes: no hay sueño automático.

## Anti-metas (sería un fracaso aunque funcione)

- Que cualquier interfaz (incluida la de esta PC) pueda cortar la radio de los demás.
- Que next, prev o la rueda del applet prendan el monitor de esta PC mientras otro escucha en el teléfono.
- Que un simple `/status` (el sondeo del applet) despierte la radio.
- Que la radio se duerma justo entre el pedido de un oyente y la apertura de su stream.

## Qué es un oyente

La radio tiene `oyentes` = oyente local (0 o 1) + conexiones de audio abiertas (stream LAN y audio de la nube, todas las calidades).

- **Local:** `monitor_local` prendido. Silenciar, pausar o llevar el volumen a 0 en esta PC apaga el monitor (con bus ya es así) y es
  "me desconecté". Subir el volumen desde 0 lo prende de vuelta (a 50, como hoy).
- **Remoto (receptor LAN en otra PC):** abrir el stream es escuchar. **Volumen de la radio en 0 en el receptor = cerrar el stream**
  (equivale a `off`); subirlo desde 0 lo reabre (`on`, con ese volumen o 50 si era 0). El volumen del sistema de esa PC no se mide.
- **Web (relay):** pausar, cerrar la reproducción o poner el volumen de la radio en 0 cierra la conexión de audio, que es lo que cuenta;
  subirlo desde 0 la reabre. El código de la web del relay no se toca acá: es una tarea aparte que cumple esta regla.

## Reglas

1. **Dormir:** con `oyentes == 0` continuo durante la gracia (`segundos_hasta_dormir`, 60 por defecto, configurable en `config.toml`),
   la radio se duerme: detiene la reproducción como el `apagar` de hoy. Es lo único que la apaga fuera de `systemctl`.
2. **Despertar por conexión:** el primer suscriptor de `/stream` (LAN) o de audio de la nube con la radio dormida la despierta con la
   última emisora (o la primera). `/status` y los sondeos no despiertan.
3. **Elegir emisora** (sintonizar, siguiente, anterior, rueda, dial, pedidos remotos):
   - Con `oyentes == 0` (dormida o contando la gracia): quien elige pasa a ser el primer oyente. En esta PC eso prende el monitor y, con volumen 0,
     lo sube a 50 (`VOLUMEN_MINIMO`). Un pedido desde la red despierta la radio y el cliente abre su stream (la gracia cubre ese tiempo).
   - Con `oyentes >= 1`: solo cambia la emisora. Nunca toca el monitor ni el volumen de esta PC.
4. **Excepción: el dial.** Abrirlo con el atajo es "escuchar acá": prende el monitor (y despierta si hace falta), haya o no otros oyentes.
5. **Subir el volumen** (atajos, `cassette vol +N`, barra del dial) con el monitor apagado lo prende (despierta si hace falta); con el monitor
   prendido solo cambia el nivel. Bajar a 0 apaga el monitor.
6. **Clic del applet y teclas Play/Pausa de MPRIS** (`alternar`): escuchar / dejar de escuchar acá. Estando dormida, despiertan y escuchan.
7. **Cliente remoto:** usa la misma regla con el `oyentes` que publica `/status`: si es 0 al elegir emisora, enciende su receptor y después
   pide la emisora; si es ≥ 1, solo la pide.
8. **Sin bus de audio:** se mantiene el comportamiento actual (encender y apagar a mano; silenciar = apagar), sin conteo ni sueño automático.

## Cambios de interfaz

- **API local (`api.py`):** se quita `/apagar` de `ACCIONES`. `/encender` pasa a ser "escuchar acá" (prende el monitor y despierta) y
  `/silenciar` "dejar de escuchar acá". `/siguiente`, `/anterior` y `/sintonizar` siguen la regla 3. `/estado` agrega `oyentes` (total) y
  `oyentes_red`, y `/status` de la LAN agrega `oyentes` a la lista pública de campos.
- **CLI (`cli.py`):** `cassette off` se quita. Nuevos `cassette stop` y `cassette start` (ver "Ciclo de vida de los servicios"). `on` y
  `mute` quedan como "escuchar" y "dejar de escuchar acá"; con el servicio caído, `on` hace antes un `start` y espera a la API.
  `cassette status` muestra los oyentes.
- **Applet:** se quita el ítem "Apagar" del menú. Con el servicio caído, el clic corre `cassette on` (levanta todo y escucha). La rueda y el menú de emisoras siguen la regla 3. El dial usa `POST /monitor {activo: true}`
  al abrirse en vez de `/encender` (regla 4). En modo remoto, el volumen 0 hace `off` y subirlo desde 0 hace `on`.
- **`lan_receiver.py`:** `volume 0` cierra mpv (como `off`); `volume N` con mpv cerrado y N>0 lo abre (como `on`).
- **MPRIS:** sin cambios de código previstos (`Stop`/`Pause` → `silenciar`, `Play` → `alternar`); se verifica con los tests.
- **Documentación:** `docs/project-context.md` y la tarea ta67 (que pasa a describir este alcance).

## Dónde va en el código

- **`Radio` (`radio.py`):** `oir_aca` pasa de "siempre verdadero salvo la red" a "quién pide": la decisión de la regla 3 la toma la radio
  con el conteo de oyentes, no el llamador. Se agrega `dormir()` (lo único que llama el vigilante; es el `_apagar` actual) y un
  `despertar_para_red()` (sintonizar la emisora actual sin tocar el monitor). `apagar` pasa a ser interno (cierre del servicio, sin bus).
- **Contador de oyentes:** `Difusores` expone el total de suscriptores y avisa al conectarse el primero (`al_primer_oyente`); el servicio
  lo conecta con `despertar_para_red`.
- **Vigilante (`servicio.py` o módulo nuevo `oyentes.py`):** hilo que cada segundo calcula `oyentes`, lleva la cuenta de la gracia y llama
  `dormir()`. La gracia también se reinicia cuando un pedido de la red despierta la radio.
- **Estado:** `encendida` queda como "está sonando" (los clientes y la LAN la siguen usando) pero ninguna interfaz la maneja directo.
  No se persiste: el servicio arranca dormido, con la emisora recordada en `estado.estacion`.

## Ciclo de vida de los servicios (`cassette stop` / `cassette start`)

Medido el 2026-11-20 en esta PC: hay tres unidades de usuario, todas `enabled` en `default.target` (arrancan con la sesión; `Linger=no`,
no hace falta cambiarlo porque el bus de audio también vive en la sesión): `cassette-fm` (~50 MB), `cassette-soloist` (~60 MB, `PartOf=` y
`After=` de `cassette-fm`: se detiene y se reinicia con ella, pero un `start` de `cassette-fm` no lo levanta) y `cassette-dj` (**~1 GB**,
sin relación con las otras). Además el contenedor Docker `cassette-ollama` (~45 MB en reposo; `restart=unless-stopped`).

- **`cassette stop`:** detiene `cassette-soloist`, `cassette-fm` y `cassette-dj`, y `docker stop cassette-ollama` si existe. Es el apagado
  definitivo: libera todo (sobre todo el 1 GB del DJ). Cada paso es "lo que pueda": una unidad o un contenedor que no existe o ya está
  parado se saltea sin error, y al final dice qué quedó parado.
- **`cassette start`:** el inverso, en este orden: `docker start cassette-ollama`, `cassette-dj`, `cassette-fm`, `cassette-soloist`. No espera
  al DJ: la radio arranca y el DJ se suma cuando termina de cargar (hoy ya pasa lo mismo en el arranque de la sesión). Es idempotente.
- **Arranque de la máquina:** ya se levanta solo con la sesión por las unidades `enabled`; no hace falta nada nuevo.
- **Sin cambios en las unidades:** no se agrega `PartOf=` al DJ, porque entonces el reinicio que pide la radio como último recurso
  (`recuperacion.py`) recargaría también el 1 GB del DJ. Por eso las listas de arriba viven en la CLI y no en systemd.
- **Quién puede levantar un servicio caído:** solo esta PC (`cassette start`, `cassette on`, el clic del applet). Con el servicio detenido,
  la notebook, el teléfono y la web no pueden despertarlo: nadie lo escucha, y eso es lo que significa "apagado definitivo".
- **Con la radio dormida (no detenida)** el DJ sigue cargado y ocupando su GB; liberarlo sin `stop` queda fuera de este diseño (posible
  tarea futura: que el servicio DJ descargue sus voces tras un rato sin pedidos).

## Enfoques considerados

- **A. Vigilante de oyentes en el servicio (elegido).** Un contador único, un hilo, dormir/despertar centralizados. Aprovecha que `Difusores`
  ya cuenta suscriptores; lo nuevo es el aviso del primer oyente y el vigilante.
- **B. Solo un temporizador de inactividad.** Lo mínimo de la tarea original. No quita los privilegios de esta PC, así que habría que agregar
  cada cambio por separado. Descartado: no cambia el concepto.
- **C. `encendida` derivada del conteo, sin bandera.** Más pura, pero obliga a modelar un estado "despertando" porque la sintonía tarda ~0,5 s
  y los oyentes se conectan con retraso. Descartado: más invasiva y sin ventaja sobre A.

## Decisiones propias (marcadas para revisar)

- Gracia de 60 s, configurable.
- Se quitan `/apagar` y `cassette off` en vez de dejarlos como alias engañosos; `cassette stop` es el apagado.
- `/status` y los sondeos no despiertan; solo `/stream`, el audio de la nube y elegir emisora.
- `cassette stop`/`start` manejan la lista completa (radio, Soloist, DJ y el contenedor de Ollama) desde la CLI, sin tocar las unidades.
  Detener Ollama se agregó por "liberar todo"; pesa poco en reposo, así que si estorba se puede sacar de la lista.
- Un receptor remoto con el volumen de la radio en 0 cierra su stream (decidido con el usuario).

## Para el que lo construya

- Orden sugerido: contador y vigilante con tests de unidad (reloj falso) → reglas 2 y 3 en `Radio` → API y CLI (con `stop`/`start`) →
  receptor y applet → docs. Hacer tarea aparte (Beans) para la regla de la web del relay.
- Nunca mostrar los argumentos del proceso de Soloist al probar `stop`/`start` (ni `systemctl status` ni `ps` con args: ver `project-context.md`).
- Detalles abiertos que decide quien implementa: nombre y sección de la opción de gracia en `config.py`; cómo evitar que el cambio de fuente
  del codificador (estática ↔ monitor, ya con `estabilidad_segundos`) pise un despertar; si `oyentes_red` va en `/estado` o solo en
  `extra_estado`.
- Tests a actualizar: `test_radio`, `test_api`, `test_cli`, `test_servicio`, `test_lan_server`, `test_lan_receiver`, `test_mpris`,
  `test_applet_estructura` y `applet/tests/logic.test.js`.
- Ojo con el applet: `ReloadXlet` no recarga `logic.js` (ver `project-context.md`); para probar cambios en él hay que reiniciar Cinnamon.
