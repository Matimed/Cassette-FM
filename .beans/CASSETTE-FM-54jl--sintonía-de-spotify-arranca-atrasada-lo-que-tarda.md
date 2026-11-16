---
# CASSETTE-FM-54jl
title: Sintonía de Spotify arranca atrasada lo que tarda Soloist en sonar
status: completed
type: bug
priority: normal
created_at: 2026-11-16T02:21:42Z
updated_at: 2026-11-16T02:33:07Z
---

La posición del primer tema se calcula al pedir el play y Soloist tarda hasta ~8 s en sonar (la estática), así que arranca atrasado; el primer tema no mide desfase y la re-sintonía tiene el mismo problema (se vio 4.4 s y 7.8 s el 2026-11-15). Idea: al llegar el position_sync de 'playing', comparar con el reloj y corregir con un seek.



Resuelto (commit c60bfa6): la causa era calcular la posición al decidir la sintonía; entre eso y el play pasan el volumen, la búsqueda del dispositivo y los PUT de shuffle y repeat (~0,6 s cada uno; más tras reiniciar). Ahora ControlSpotify.reproducir recibe una función y la posición se calcula justo antes del play. Medido contra la agenda: de 1,6–1,9 s de atraso a ~0,4 s (lo que tarda Soloist del play al sonido).
