# Etapa 7a — Peticiones del público por la cola de Spotify — diseño

## Intención

Mientras suena una emisora de Spotify, el usuario encola un tema desde la app de Spotify (es lo que ya hace por
costumbre). La radio lo trata como una **petición del público**: el DJ lo presenta como «una petición especial» y la
agenda de la emisora **se reacomoda** para que, terminado el pedido, la emisora siga exactamente donde estaba, sin
perder temas. Es la primera parte de la etapa 7 (pedidos al DJ); los pedidos en emisoras locales, por CLI o por
búsqueda, y el skip, quedan para después y este diseño les deja el lugar.

## Cómo es hoy

- La agenda de cada emisora es determinista: `secuencia(estacion, instante)` en `agenda.py` dice qué tema suena y
  desde qué segundo; todo (reproductores, planificador del DJ, locutor, control de desfase) la usa.
- En una emisora de Spotify la radio manda una lista `uris` (~100 temas de la agenda) y **no usa la cola** de
  Spotify, que queda para el usuario (decisión de la etapa 4). Un tema encolado suena después del actual y Spotify
  sigue solo con la lista. Hoy eso funciona a medias: `_hay_que_resintonizar` deja sonar el tema ajeno, pero cuando
  vuelve un tema de la agenda ve un desfase igual a lo que duró el pedido y **re-sintoniza al reloj**, salteándose
  los temas que «sonaron» mientras tanto; el DJ no lo anuncia.
- Soloist manda `queue_changed` con `upcoming` (lista de `{source, item}`; `source` distingue `queue` de `context` y
  `autoplay`) y `track_changed` con el `item` que empieza. Los datos del ítem (`decorations.identity.name`,
  `decorations.playback.duration_ms`) no traen artista seguro: la metadata completa sale de la Web API
  (`GET /tracks/{id}`, `market=from_token`).
- El DJ: el `Planificador` elige un hueco (una transición futura, con `margen_minutos` de anticipación), pide la
  intervención al servicio DJ (`armar_pedido` → `POST /intervenciones`) y el `Locutor` la dice anclada a la clave del
  tema destino. Si la agenda de una emisora cambia (`al_rescan`, firma de la estación), las intervenciones reservadas
  de esa emisora se descartan.

## Decidido con el usuario

- Empezar por Spotify con la cola de la app.
- El DJ dice que es **una petición especial**.
- Anuncio **antes** (sobre el comienzo del pedido) si hay tiempo; si no llega, **al final** (sobre el comienzo del
  tema que sigue: «eso fue una petición especial…»).
- La agenda se reacomoda con un **corrimiento por emisora** (enfoque 1, abajo).
- Si a mitad de un pedido el usuario cambia de emisora unos segundos y vuelve, **sigue el pedido** en el segundo
  justo (la emisora «siguió sonando» el pedido, como sigue sonando todo).

## Enfoques

1. **Corrimiento por emisora + pedidos en curso (elegido).** Cada emisora lleva un corrimiento acumulado y la lista
   de los pedidos que todavía no terminaron (tema + epoch en que empezó). La agenda los respeta: durante un pedido
   suena el pedido; después, la agenda sigue con el corrimiento sumado. Un pedido terminado se pliega al corrimiento
   y se olvida. Como todo calcula con `secuencia`, todos los consumidores lo siguen solos. Sirve igual para pedidos
   locales futuros.
2. Lista completa de inserciones (historial) que la agenda intercala al recorrerse: la agenda «sabe» qué pedidos
   sonaron, pero cada cálculo recorre el historial y es bastante más código para el mismo resultado audible.
   Descartado.
3. Que el pedido reemplace lo que venía sin mover el reloj: se pierden temas de la agenda. Descartado.

## Diseño

### Agenda con pedidos

- `Estacion` suma dos campos con default (no cambia nada para quien no los usa):
  - `corrimiento: float = 0.0` — segundos que la emisora va atrasada respecto del reloj por los pedidos ya sonados.
  - `pedidos: tuple[Pedido, ...] = ()` — pedidos sin terminar, en orden; `Pedido(pista: Pista, inicio: float)`.
- `secuencia(estacion, instante)` (y por lo tanto `transiciones` y `desfase`) pasa a: si `instante` cae dentro de un
  pedido (`inicio <= instante < inicio + duracion`), da ese pedido desde `instante - inicio` y después sigue la agenda
  como si el reloj se hubiera detenido durante el pedido; fuera de los pedidos, usa `instante - corrimiento - (suma
  de los pedidos que ya empezaron antes de instante)`. Sin pedidos ni corrimiento, el resultado es idéntico al de hoy
  (los tests actuales de agenda no cambian).
- La firma de la estación que usa el planificador para detectar cambios de agenda resume la **línea de tiempo
  futura**: las pistas más el corrimiento total contando los pedidos en curso por su duración nominal. Así, al empezar
  un pedido la firma cambia (lo planificado para después quedó corrido y se descarta), pero al plegarse un pedido que
  duró lo que debía no cambia nada; si se salteó o se cortó, sí cambia. Decisión de Claude.
- Las intervenciones de **petición** («antes» y «después») no se descartan por esos cambios de agenda: están ancladas
  a la clave de su tema (el pedido, o el que lo sigue), que sigue siendo válida. Tampoco se borra la última
  intervención cuando la que la marcó es una petición. Solo se descartan las normales. Decisión de Claude.

### Estado guardado

- `Estado` suma `pedidos: dict[str, {corrimiento, pedidos: [{uri, titulo, artista, cancion, album, isrc, duracion,
  inicio}]}]` por nombre de emisora, en `estado.json`. Se guarda en cada cambio. Al arrancar y en cada rescan, la radio
  aplica lo guardado a las estaciones escaneadas (por nombre). Así un reinicio en medio de un pedido lo retoma.
- Un pedido cuyo fin ya pasó se pliega al corrimiento al cargar o al rescan (y en cada cambio), para que la lista
  quede corta.

### Detección del pedido (reproductor de Spotify)

- **Qué es un pedido: lo que vino de la cola**, no «cualquier URI ajena». El reproductor recuerda las URIs que
  `queue_changed` mostró con `source == "queue"` (y lo que diga `track_changed`, si trae el origen; se fija en la
  captura de eventos). Un `track_changed` de una de esas URIs, con la emisora sintonizada y lo pedido ya sonando, es un
  **pedido que empieza** en ese instante (epoch del evento menos la posición, si viene), aunque el tema también sea de
  la playlist de la emisora o sea justo el que venía en la agenda. El reproductor avisa a la radio con un callback
  nuevo `al_pedido(pista, inicio, estacion)`. No se re-sintoniza.
- Un tema ajeno que **no** vino de la cola (el usuario puso otra playlist o un álbum en «cassette-fm» desde la app) no
  es un pedido: se deja sonar sin tocar la agenda, como hoy, y al cambiar de emisora la radio recupera el control
  (lo que el usuario pidió en la etapa 4). Decisión de Claude a partir de eso.
- La radio agrega el `Pedido` a la estación (estación nueva con `dataclasses.replace`), la reemplaza en su lista y en
  el reproductor, guarda el estado y avisa al planificador (cambio de agenda → descarta lo reservado de esa emisora).
- Cuando vuelve un tema de la agenda (o empieza otro pedido), el pedido anterior **terminó**: se pliega con su
  duración **real** (inicio del tema nuevo − inicio del pedido), no la nominal. Así un pedido salteado desde la app o
  cortado a la mitad deja la agenda bien, y dos pedidos seguidos se encadenan. Con eso el desfase da ~0 y no hay
  re-sintonía; si igual queda fuera de tolerancia, se re-sintoniza como hoy.
- Un pedido que el reproductor cree en curso pero que nunca termina con un evento (la radio se apagó, se cambió de
  emisora) termina solo por la agenda: su duración nominal. Así, volver a mitad del pedido lo retoma (la lista `uris`
  que se manda al sintonizar empieza por el pedido en la posición justa y sigue con la agenda), y volver después lo
  da por terminado.
- La pista del pedido se completa con la Web API (`/tracks/{id}`: artistas, título, álbum, ISRC, duración) en segundo
  plano; si falla, queda con lo que trae el evento (nombre y duración) y el DJ usa la plantilla sin artista o no
  anuncia (ver abajo).

### Anuncio del DJ

- **Antes**: apenas llega un `queue_changed` con un tema nuevo de `source == "queue"` como próximo (el primero de
  `upcoming`), el reproductor lo informa (`al_encolado(pista, estacion)`). El planificador, si la emisora es la
  sintonizada y el DJ está activo, crea un trabajo prioritario para la transición «tema actual → pedido»: hueco con
  `inicio_tema` = fin estimado del tema actual (posición real), tipo `peticion: "antes"`. Se piden la metadata y la
  intervención al toque. Si queda menos de un margen mínimo (configurable, `peticion_margen_segundos`, default 30)
  hasta el fin del tema actual, se va directo al «después».
- La intervención «antes» se ancla a la clave del pedido (su URI), como cualquier otra. Si al empezar el pedido no
  está lista (no llegó, falló), se cancela y se pide la **«después»**: hueco en la transición «pedido → tema que
  sigue» (que la agenda ya conoce porque el pedido está en curso), con `peticion: "despues"` y `anterior` = el
  pedido.
- Un pedido que se saca de la cola antes de sonar: su intervención «antes» se descarta al ver que empieza otra cosa.
- El anuncio cuenta como la última intervención para la frecuencia del DJ, y desplaza cualquier intervención
  normal planificada en esos huecos (se descartan por el cambio de agenda).
- Servicio DJ: el pedido suma `"peticion": "antes" | "despues"` (opcional; sin él, todo igual que hoy).
  - Plantillas nuevas en es/en para cada caso («Llega una petición especial: …», «Eso fue una petición especial: …,
    y ahora …»).
  - Modo LLM: el prompt dice que es una petición del público (antes: presentarla; después: cerrarla y presentar el
    siguiente). El verificador no cambia.
- Varios pedidos seguidos: cada uno con su anuncio, si entra sin superponerse (los huecos ocupados ya se respetan).

### Bordes

- Pedidos encolados con la radio en una emisora local o apagada: la cola es de la cuenta; si suenan cuando se
  sintoniza una emisora de Spotify, son pedidos de esa emisora a partir de que empiezan (sin anuncio «antes» si no
  hubo `queue_changed` con la emisora sintonizada).
- El autoplay de Spotify (`source == "autoplay"`) no es un pedido: no debería pasar porque la lista se renueva antes
  de terminarse; si pasa, se re-sintoniza como hoy.
- Emisoras locales: no cambian (sin cola). El modelo de agenda ya sirve para pedidos locales futuros.

## Fuera de alcance

Pedidos en emisoras locales, por CLI/applet o por búsqueda; skip del tema actual; mostrar los pedidos en la UI.

## Verificación

- Antes de construir la detección, capturar con el usuario eventos reales de Soloist al encolar desde la app
  (`queue_changed` y `track_changed` del pedido y del tema siguiente), con la radio sonando una emisora de Spotify,
  para fijar los campos en los tests.
- Al final, prueba real: encolar con tiempo (anuncio antes), encolar sobre el final (anuncio después), cambiar de
  emisora a mitad del pedido y volver (sigue el pedido), saltear el pedido desde la app (la agenda sigue sin
  re-sintonía), reiniciar la radio a mitad del pedido.

## Para quien construye

Dónde vive el plegado de pedidos (estado vs. radio), cómo se estima el fin del tema actual para el hueco «antes», el
texto exacto de las plantillas, y cómo se testea el reloj de los eventos.
