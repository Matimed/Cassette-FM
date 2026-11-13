---
# CASSETTE-FM-cbtc
title: 'Biblioteca: escaneo de estaciones y duraciones'
status: completed
type: task
priority: normal
created_at: 2026-11-13T23:03:54Z
updated_at: 2026-11-13T23:13:19Z
parent: CASSETTE-FM-u2yr
blocked_by:
    - CASSETTE-FM-na6t
---

Subcarpeta directa = estación (recursiva adentro); ignora ocultas, sueltos e ilegibles. Duraciones con mutagen y caché por ruta+mtime+tamaño en ~/.cache/cassette-fm/. Campo `fuente` (local). Con TDD (superpowers:test-driven-development).
