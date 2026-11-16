---
# CASSETTE-FM-rvd4
title: 'Peticiones: casos menores pendientes de la etapa 7a'
status: completed
type: task
priority: low
created_at: 2026-11-16T02:21:42Z
updated_at: 2026-11-16T03:25:51Z
parent: CASSETTE-FM-80sa
---

De la revisión final de 7a: el antes de un tema sacado de la cola sin encolar otro (y el después de un pedido salteado) vence mudo y frena las normales hasta su fin; un pedido puede reemplazar el trabajo normal en curso de otra emisora sin cancelarlo; un ítem de Soloist sin nombre pero con artista se anunciaría con la URI; carrera rescan/al_cambiar_agenda deja pistas viejas hasta el próximo rescan.



Hecho (commits a9f4c7c, 5f53f7e): sacar el encolado de la cola descarta su antes; el después de un pedido salteado se descarta; un pedido cancela el trabajo normal de otra emisora; ítem sin nombre no se anuncia; la radio conserva sus pistas al cambiar la agenda. Probado con el usuario el 2026-11-16.
