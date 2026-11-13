---
# CASSETTE-FM-40h0
title: API para crear y borrar emisoras
status: todo
type: feature
created_at: 2026-11-13T23:32:53Z
updated_at: 2026-11-13T23:32:53Z
---

Endpoints para crear una emisora (nombre + fuente) y borrarla. La fuente es un directorio de música o el link de una playlist de Spotify. Hoy una estación es solo una subcarpeta de la raíz; esto introduce emisoras configuradas y persistidas (en config o estado) que conviven con las carpetas. El caso del link de Spotify depende de la etapa 4 (CASSETTE-FM-4yzi); el de directorio no. Pendiente: decidir dónde se guardan y qué pasa con las subcarpetas de ~/Música ya existentes.
