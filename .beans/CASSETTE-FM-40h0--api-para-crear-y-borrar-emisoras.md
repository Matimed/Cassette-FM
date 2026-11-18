---
# CASSETTE-FM-40h0
title: API para crear y borrar emisoras
status: completed
type: feature
priority: normal
created_at: 2026-11-13T23:32:53Z
updated_at: 2026-11-18T02:53:38Z
---

Estaciones como objetos en un JSON (hoy son subcarpetas de la raíz de música): nombre, fuente (un directorio en cualquier ruta o el link de una playlist de Spotify) y los ajustes del DJ de esa estación (voz, idioma, personalidad, frecuencia). La voz se elige al crear la estación. La API permite crearlas (nombre + fuente + voz) y borrarlas. El caso del link de Spotify depende de la etapa 4 (CASSETTE-FM-4yzi); el de directorio no. Pendiente: dónde se guarda el JSON y qué pasa con las subcarpetas de ~/Música ya existentes. Contexto: docs/superpowers/specs/2026-11-13-cassette-fm-design.md (sección 'Evolución prevista: estaciones como objetos') y el diseño de la etapa 3 (el DJ lee su configuración por estación a través de una sola función para no acoplarse a las carpetas).



## Resuelto
Las emisoras viven en `~/.config/cassette-fm/estaciones.json` y se manejan con `cassette nueva`, `borrar`, `renombrar`, `icono` y `voces`, y desde el applet ("Nueva emisora…"). Se hizo por CLI, sin endpoints HTTP de alta/baja.
