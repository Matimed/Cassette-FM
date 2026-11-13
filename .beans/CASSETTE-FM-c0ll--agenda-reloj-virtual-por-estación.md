---
# CASSETTE-FM-c0ll
title: 'Agenda: reloj virtual por estación'
status: todo
type: task
created_at: 2026-11-13T23:03:54Z
updated_at: 2026-11-13T23:03:54Z
parent: CASSETTE-FM-u2yr
blocked_by:
    - CASSETTE-FM-na6t
---

Función pura (estación, pistas, instante) -> (pista, segundo, siguientes). Época fija 2026-01-01Z, ciclo k mezclado con semilla sha256(estación, k), sin repetir tema en el borde entre ciclos. Con TDD (superpowers:test-driven-development).
