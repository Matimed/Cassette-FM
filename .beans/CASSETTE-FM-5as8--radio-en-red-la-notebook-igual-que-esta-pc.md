---
# CASSETTE-FM-5as8
title: 'Radio en red: la notebook igual que esta PC'
status: todo
type: feature
priority: high
created_at: 2026-11-18T03:37:24Z
updated_at: 2026-11-18T03:37:24Z
parent: CASSETTE-FM-abja
---

Primera entrega del diseño docs/superpowers/specs/2026-11-18-radio-en-red-design.md (prioridad del usuario). Esta PC queda como servidor y la notebook corre la radio en modo cliente con backend Soloist, sin Docker, LLM ni TTS, y suena igual que acá.
Incluye: servidor con roles (dueño por loopback, oyente con clave), endpoints de lectura (catálogo versionado, agenda, intervenciones y clips, presencia), modo cliente con catálogo y agenda remotos, voces remotas, ajustes del applet (dirección y clave de oyente), instalador de cliente y verificación de pasar de dispositivo.
Sugerencia de planes en el diseño: 1 servidor y roles, 2 modo cliente, 3 voces, 4 applet e instalador.
