# Cierre de las peticiones (etapa 7a): anuncio combinado y casos menores

Diseño corto, aprobado por el usuario el 2026-11-15. Cierra las tareas de Beans CASSETTE-FM-0av0 y CASSETTE-FM-rvd4
antes de pasar a los pedidos por nombre (CASSETTE-FM-8cm0). Parte de
[`2026-11-15-peticiones-spotify-design.md`](2026-11-15-peticiones-spotify-design.md).

## Por qué

En la prueba real de 7a quedaron cabos sueltos: dos pedidos seguidos dejan al primero sin mención propia, y algunos
anuncios quedan huérfanos (no suenan pero ocupan el lugar y frenan las intervenciones normales hasta vencer).

## Anuncio combinado

- Hoy, si el tema que sigue a un pedido es otro pedido, gana el «antes» del segundo y el primero solo llega al DJ como
  «tema anterior», sin decir que fue un pedido.
- Nuevo modo de petición **`seguidas`** en el servicio DJ: el tema anterior fue una petición y el que sigue también.
  Requiere `anterior` (como `despues`).
  - Plantillas: una oración que cierra el anterior y abre el siguiente, p. ej. «Eso fue una petición especial: A de X.
    Y llega otra.» / «That was a special request: A by X. And here comes another one.»
  - LLM: la indicación del prompt dice las dos cosas (el anterior fue una petición, mencionalo; este también lo es,
    presentalo como tal) y el anterior va siempre en el prompt.
- El planificador pide `seguidas` en vez de `antes` cuando el tema actual (el `anterior` del anuncio) es un pedido en
  curso de la emisora.
- **Aproximaciones descartadas:** reusar el «después» del primero apuntado al segundo (no lo presenta como petición);
  dos clips seguidos (largo, y se pisan en el mismo borde).
- **Fuera de alcance:** dos encolados con menos de `peticion_margen_segundos`: no hay tiempo para generar un anuncio
  antes del segundo, así que el primero sigue sin mención (el «después» del segundo lo nombra solo a él).

## Casos menores

1. **Tema sacado de la cola sin encolar otro:** el reproductor avisa cuando el encolado ya avisado desaparece de la
   cola sin haber empezado (ignorando el `queue_changed` transitorio de Soloist con `spotify:meta:…`); el planificador
   descarta su «antes» (pendiente, en preparación o reservado) y lo olvida (si se vuelve a encolar, se avisa de nuevo).
2. **«Después» de un pedido salteado:** cuando cambia la agenda sin pedido nuevo (se plegó), los «después» de esa
   emisora cuyo tema destino ya no empieza dentro de la tolerancia de su lugar se descartan. Decisión del usuario: no
   se mencionan (lo saltó), en vez de mover el anuncio.
3. **Pedido con un trabajo normal de otra emisora en curso:** se cancela en el servicio DJ antes de reemplazarlo (hoy
   se pierde sin cancelar).
4. **Ítem de Soloist sin nombre:** cuenta como pedido para la agenda, pero sin nombre de canción (no se anuncia);
   el título no es la URI.
5. **Rescan que se cruza con un pedido:** la radio es la dueña de las pistas (rescan) y el reproductor del corrimiento y
   los pedidos: al cambiar la agenda, la radio toma solo esos dos campos sobre su emisora.

## Lo que queda al implementador

Nombres internos, la redacción exacta de las frases (siguiendo el estilo de `_PETICION`) y los tests.
