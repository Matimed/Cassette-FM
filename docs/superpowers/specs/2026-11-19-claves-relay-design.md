# Claves del relay — diseño

Cambio sobre el relay en la nube ([`2026-11-19-relay-nube-design.md`](2026-11-19-relay-nube-design.md)) y el puente
de la PC ([`2026-11-19-puente-nube-design.md`](2026-11-19-puente-nube-design.md)). Nada de esto está desplegado
todavía, así que no hay compatibilidad hacia atrás que cuidar.

## Para qué

Hoy el relay tiene una sola clave de oyentes (`APP_PASSWORD`) y cualquiera que entra puede todo. El usuario quiere
repartir acceso a varias personas, distinguir quién solo escucha de quién además cambia de emisora, y poder quitarle el
acceso a una persona sin cambiar la clave de todos. En el entorno del relay tiene que quedar una sola clave de
oyentes: la maestra.

## Decisiones del usuario

- Una clave maestra en el entorno del relay; el resto de las claves se crean y se borran desde esta PC.
- Dos permisos: **escucha** (escuchar, ver estado y logos) y **completa** (además sintonizar, siguiente, anterior).
- La lista de claves vive en la PC (enfoque A, abajo).
- Aprobó el esquema que sigue (CLI, archivo, maestra renombrada, corte inmediato al borrar, gracia al despertar).

## Restricciones

- Render free no tiene disco y duerme el relay a los 15 min sin tráfico: lo que se cree en el relay se pierde.
- Claves fuera de logs, URLs y argv (regla del proyecto). En el relay no se guardan claves, solo huellas.
- Ni la PC ni el relay guardan las claves generadas en claro: solo su huella (SHA-256). Se muestran una vez, al crearlas.
- Los nombres de las personas no salen de la PC (el relay recibe id, permiso y huella).

## Objetivos, no objetivos, anti-objetivos

- **Objetivos:** crear, listar y borrar claves desde la PC; permiso escucha/completa aplicado en el relay; borrar una
  clave echa a quien la usa en el momento (API y audio); la maestra funciona siempre, aun sin la PC conectada.
- **No objetivos:** cambiar el permiso de una clave (se borra y se crea otra); renombrar; ver quién escucha o cuándo se
  usó una clave por última vez; vencimiento de claves; administrar claves desde el teléfono.
- **Anti-objetivos:** que cada vez que Render despierta el relay todos tengan que volver a poner la clave; que una
  clave borrada siga sirviendo hasta que venza la cookie; que el relay dependa de un servicio externo para guardar.

## Enfoques considerados

- **A. La lista vive en la PC (elegido).** La CLI escribe un archivo local; el puente le manda la lista al relay por
  el control (al conectar y cuando cambia). Sin dependencias nuevas; sin la PC no hay radio igual.
- **B. La lista vive en el relay**, con una ruta de administración protegida por la maestra. Sin disco en Render, haría
  falta una base externa gratuita: una cuenta y una pieza más que pueden fallar.
- **C. Claves firmadas sin estado** (la clave lleva su permiso firmado con la maestra). Borrar una clave igual necesita
  una lista de revocadas guardada en algún lado: cae en A o B, con más complejidad.

## Diseño

### Archivo de claves (PC)

`~/.config/cassette-fm/claves.json` (al lado de `nube.token`; `Rutas.claves`), modo 0600, escritura atómica
(tmp + `os.replace`, como `lan_acceso._escribir`):

```json
{"claves": [{"id": "3f9a1c2b", "nombre": "Mamá", "permiso": "escucha",
             "huella": "<sha256 hex de la clave>", "creada": "2026-11-19T21:04:00-03:00"}]}
```

- `id`: 8 hex al azar, único. Es lo que viaja en la cookie y al relay.
- `nombre`: 1 a 40 caracteres, sin saltos de línea; único sin distinguir mayúsculas ni espacios de los bordes.
- `permiso`: `"escucha"` o `"completa"`.
- Archivo ausente = lista vacía. Archivo roto = error claro en la CLI; el servicio lo registra y sigue con la última
  lista buena (o vacía si nunca hubo una).

### Formato de la clave

16 caracteres del alfabeto base32 de Crockford en minúscula (`0123456789abcdefghjkmnpqrstvwxyz`: sin `i`, `l`, `o`,
`u`), en grupos de 4: `k7qm-…` (80 bits; se tipea una vez en el teléfono porque la sesión dura 180 días). Al comparar,
el relay pasa la clave dada a minúscula y le saca espacios y guiones antes de calcular la huella, para que tipearla en
el teléfono no falle por eso. La huella se calcula sobre esa forma normalizada (16 caracteres, sin guiones). La
maestra no se normaliza: se compara tal cual.

### CLI (`cassette claves`)

- `cassette claves` — lista: nombre, permiso, fecha de creación. Si no hay ninguna, lo dice y recuerda la maestra.
- `cassette claves nueva NOMBRE [--escucha | --completa]` — por defecto `--escucha`. Imprime la clave una sola vez,
  con una línea que dice que no se vuelve a mostrar. Nombre repetido = error, sin tocar el archivo.
- `cassette claves borrar NOMBRE [--si]` — pide confirmación como `cassette borrar` (sin terminal, exige `--si`).
- La CLI solo escribe el archivo; no habla con el servicio. Si `[nube]` está apagado, avisa que las claves rigen
  cuando se active.

### Servicio y puente (PC)

- `iniciar_nube` ya tiene un hilo de revisión cada 1 s (la clave de la nube). Suma la lectura de `claves.json`: cuando
  el contenido cambia, le pasa al puente la lista nueva (`PuenteNube.claves(lista)`), sin reconectar.
- El puente manda `{"tipo": "claves", "claves": [{"id", "permiso", "huella"}, …]}` justo después de `hola` en cada
  conexión, y de nuevo cuando la lista cambia (por la cola de salida existente). Sin nombres ni fechas.
- `PROTOCOLO` queda en 1: no hay versiones desplegadas con las que chocar.

### Relay

**Configuración.** `APP_PASSWORD` pasa a ser `MASTER_PASSWORD` (mismo requisito: al menos 8 caracteres). Cambiarla
cierra todas las sesiones, como hoy. `INGEST_TOKEN` no cambia.

**Claves conocidas.** `Acceso` guarda la maestra y la última lista recibida (`id → (permiso, huella)`), más si ya
recibió alguna lista desde que arrancó. La lista no se borra cuando la PC se desconecta.

**Mensaje `claves` por el control.** Se valida entero: lista de a lo sumo 200 objetos, `id` de 8 hex sin repetir,
`permiso` válido, `huella` de 64 hex. Si algo no valida, se ignora el mensaje entero con un aviso en el log (sin
contenidos) y sigue rigiendo la lista anterior.

**Probar una clave** (Bearer o `entrar`): primero la maestra (`compare_digest`), después la huella de la clave
normalizada contra las de la lista. Resultado: el acceso (`id`, `permiso`), "mal" o "bloqueado". La maestra es
`id = "maestra"`, permiso completa. El bloqueo por intentos (5 fallos en 60 s, 60 s) sigue igual y global. Antes de
la primera lista, una clave generada no entra (solo la maestra): la PC la manda a los pocos segundos de conectar.

**Cookie de sesión:** `<id>.<permiso>.<vence>.<hmac>`, firmada con la llave derivada de la maestra (como hoy).
Es válida si la firma y el vencimiento están bien y además:

- `id == "maestra"`, o
- ya llegó una lista y el `id` está en ella (rige el permiso de la lista), o
- todavía no llegó ninguna lista desde que arrancó el relay (rige el permiso firmado en la cookie). Es la gracia al
  despertar: sin ella, cada despertar de Render echaría a todos.

Cookies con el formato viejo (`<vence>.<hmac>`) no valen: nada estaba desplegado. Una cookie que no vale da 401 pero
no cuenta como intento fallido para el bloqueo (no es alguien probando claves).

**Permisos en la API.** El middleware deja en el pedido el acceso (`id`, `permiso`). `sintonizar`, `siguiente` y
`anterior` con permiso escucha devuelven 403 `{"error": "esta clave es solo para escuchar"}`. `GET /api/estado`
suma `"permiso": "escucha" | "completa"`.

**Corte al borrar.** Cada oyente de audio queda anotado con el `id` de su acceso. Cuando llega una lista sin un `id`
que estaba, se cierran en el acto los oyentes con ese `id` (su próximo pedido a la API da 401 por la cookie). Con la
primera lista después de despertar pasa lo mismo: se cortan los oyentes que entraron por la gracia con un `id` que la
lista no trae. Los oyentes con la maestra no se tocan nunca.

**Logs:** sin claves ni huellas. Se puede registrar el `id` y el permiso al entrar ("entró 3f9a1c2b (escucha)") y la
cantidad de claves recibidas.

### Página de prueba

Lee `permiso` de `/api/estado` y esconde los botones de emisora, siguiente y anterior con permiso escucha (sigue
mostrando la emisora actual y los logos). Un 403 en una orden se muestra como mensaje.

### Documentación

`relay/README.md` (variable `MASTER_PASSWORD`, sección de claves y permisos, tabla de la API con 403 y `permiso`),
`README.md` del proyecto (comando `cassette claves`), spec del puente (mensaje `claves`) y `docs/project-context.md`.

## Pruebas

- Archivo y CLI: crear (formato, permiso por defecto, huella guardada, clave no guardada, modo 0600), nombre repetido,
  borrar con y sin `--si`, listar vacío, archivo roto.
- Servicio: un cambio en `claves.json` llega al puente sin reconectar; archivo roto mantiene la lista anterior.
- Puente: `claves` sale después de `hola` en cada conexión y cuando cambia la lista; sin nombres.
- Relay `Acceso`: maestra, clave de escucha, clave completa, normalización (mayúsculas, guiones, espacios), clave
  borrada, cookie con id desconocido antes y después de la primera lista, cookie manipulada (permiso cambiado), bloqueo.
- Relay API: 403 de las órdenes con escucha, `permiso` en estado, corte del audio al borrar la clave en uso (y no de la
  maestra), mensaje `claves` inválido ignorado.
- Punta a punta: `cassette claves nueva` → el puente manda la lista → la clave entra al relay real; borrarla corta el
  audio.

## Lo que queda al builder

Nombres internos, dónde vive el código de claves en la PC (módulo nuevo o `lan_acceso`), forma exacta de la salida de
la CLI, y cómo el middleware pasa el acceso al handler.

## Decisiones que tomé yo (para revisar)

- `MASTER_PASSWORD` en lugar de `APP_PASSWORD`.
- Formato de clave: 16 caracteres base32 en grupos de 4, normalizada al comparar.
- Permiso por defecto de `nueva`: escucha (el más seguro).
- La CLI no habla con el servicio; el servicio revisa el archivo cada 1 s.
- Los nombres no viajan al relay.
- Gracia al despertar: antes de la primera lista, valen las cookies con su permiso firmado.
- Mensaje `claves` inválido: se ignora entero y sigue la lista anterior. Tope de 200 claves.
- `PROTOCOLO` sigue en 1.
