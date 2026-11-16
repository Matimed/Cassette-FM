---
# CASSETTE-FM-54jl
title: Sintonía de Spotify arranca atrasada lo que tarda Soloist en sonar
status: todo
type: bug
created_at: 2026-11-16T02:21:42Z
updated_at: 2026-11-16T02:21:42Z
---

La posición del primer tema se calcula al pedir el play y Soloist tarda hasta ~8 s en sonar (la estática), así que arranca atrasado; el primer tema no mide desfase y la re-sintonía tiene el mismo problema (se vio 4.4 s y 7.8 s el 2026-11-15). Idea: al llegar el position_sync de 'playing', comparar con el reloj y corregir con un seek.
