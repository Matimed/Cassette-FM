---
argument-hint: "<descripción de la tarea>"
description: Crea una tarea nueva en Beans en el store integrado de este repo (cassette-fm), ubicándola bajo la épica correcta y commiteando el alta junto con el resto del historial del proyecto.
---

# Beans: crear tarea (cassette-fm)

Versión de este repo del comando global `/beans:create`, simplificada porque en cassette-fm el store
de Beans vive **integrado dentro de este mismo repo** (no es un repo de datos separado como en
KIPIN): no hace falta resolver casos de repo independiente ni remotes propios de Beans.

La descripción de la tarea viene en los argumentos de esta skill. Si vino vacía, pedísela al usuario antes de seguir.

No toques código funcional del proyecto ni mezcles el alta del bean con otros commits. El único commit que hacés es el de los archivos de Beans (Paso 5).

---

## Paso 0 — Verificar que Beans está inicializado

```bash
test -f "$(git rev-parse --show-toplevel)/.beans.yml" && echo existe || echo falta
```

Si falta, Beans no está inicializado todavía en este repo — avisá y no sigas (no es tu trabajo correr `beans init` sin que te lo pidan).

Si existe, traé el estado actual:

```bash
beans list --json
```

## Paso 1 — Relevar el estado actual

Con el `beans list --json` del paso 0 ya tenés todos los beans existentes. Para cada epic (`-t epic`) que parezca relacionado por tema con la tarea nueva — no solo por coincidencia de palabras — leé su cuerpo completo:

```bash
beans show --json <id> [id...]
```

## Paso 2 — Decidir dónde va

- **Encaja en un epic existente**: creala con `--parent <epic-id>`.
- **No encaja en ninguno, pero tiene entidad propia** (es razonable pensar que en el futuro se agreguen más tareas relacionadas): creá primero el epic nuevo (`-t epic`, `-s todo`, cuerpo corto explicando el alcance) y la tarea como su hijo.
- **Es un ítem suelto** (una decisión puntual, sin entidad de agrupación): creala sin `--parent`.

## Paso 3 — Completar los metadatos

- **Tipo** (`-t`): `bug` si describe un comportamiento incorrecto existente, `feature` si es una pantalla/capacidad nueva de cara al usuario, `task` para el resto.
- **Prioridad** (`-p`): solo si el pedido la sugiere explícitamente (algo bloqueante → `critical`/`high`). Si no hay señal, dejá `normal` (el default).
- **Estado** (`-s`): `todo` salvo que la tarea sea en sí una decisión a discutir con el equipo, en cuyo caso `draft`.
- **Tag**: mirá los tags que ya traen los beans existentes de este proyecto. Si hay uno consistente (todos o casi todos lo comparten), aplicalo también con `--tag`. Si el proyecto no usa tags todavía, no le inventes uno.
- **Cuerpo** (`-d`): 2-4 líneas de contexto concreto, en el mismo nivel de detalle que el resto del backlog — no repitas el título.

## Paso 4 — Relaciones

Revisá si la tarea nueva bloquea o depende de alguna existente (`--blocked-by` / `--blocking`) y si alguna tarea existente debería pasar a depender de esta nueva. Usá `beans update <id> --blocking <otro-id>` / `--blocked-by <otro-id>` según corresponda. No rompas ni borres relaciones que ya existían — solo agregá.

## Paso 5 — Commit

En cassette-fm `.beans` vive dentro del repo del proyecto (no tiene `.git` propio), así que el commit se hace **solo** sobre los archivos de Beans, nunca con `-A` ni `add .` — eso arrastraría cualquier otro cambio de código que el usuario tenga pendiente en el working tree.

Este repo no usa Conventional Commits (`feat:`, `fix:`, etc.), sino mensajes descriptivos en español. Antes de commitear, confirmá el estilo vigente y replicalo — no inventes un prefijo `beans:` ni `chore:` que el repo no usa:

```bash
git log --oneline -15
```

```bash
git add .beans .beans.yml
git commit -m "<mensaje describiendo el alta, siguiendo el estilo del repo>"
```

## Paso 6 — Reportar

2-3 líneas: dónde quedó (epic al que se sumó, epic nuevo creado, o standalone), tipo, prioridad, si se agregó alguna dependencia, y si se pudo commitear. No hace falta mostrar el JSON completo.
