---
# CASSETTE-FM-zuej
title: 'Etapa 3, parte 2b: radio, planificador y cliente del servicio DJ'
status: completed
type: feature
priority: normal
created_at: 2026-11-14T01:57:49Z
updated_at: 2026-11-14T03:28:56Z
parent: CASSETTE-FM-p6zn
blocked_by:
    - CASSETTE-FM-jd7u
---

En la radio: planificador (elige el hueco segun la frecuencia configurable por temas o por minutos; el valor por defecto es una configuracion general en [dj.frecuencia] que cada estacion puede pisar), un solo trabajo en curso con 'iniciado = ya se hizo el POST', un pendiente para la estacion sintonizada, cliente HTTP con espera creciente ante fallos, voz/idioma/personalidad por estacion, retoma por id tras reiniciar, y comando 'cassette dj pedir'. Depende de la parte 2a. Plan: docs/superpowers/plans/2026-11-13-etapa-3-parte-2b-planificador.md.
