# La voz del DJ entre dos temas — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el DJ hable sobre el empalme entre dos temas (posiciones `inicio`, `entre`, `final`, o `mixto` al azar) y que lo que dice se adapte a dónde cae la voz.

**Architecture:** La intervención se ancla al *corte* entre el tema de origen y el de destino, no al arranque del destino. El planificador sortea la posición, se la manda al servicio DJ (que adapta el texto) y, con el clip listo, calcula el inicio real de la voz. El locutor dispara la voz con un temporizador armado en el arranque del tema de origen (o del destino, en `inicio`), corregido con el desfase medido.

**Tech Stack:** Python 3.12, pytest (TDD), mpv por socket, Soloist por WebSocket. Tests: `python3 -m pytest -q <ruta>` (la suite completa tarda ~2,5 min; línea base: 2436 pasan).

**Spec:** [`docs/superpowers/specs/2026-11-20-voz-entre-temas-design.md`](../specs/2026-11-20-voz-entre-temas-design.md). Leerla entera antes de empezar. El contexto del proyecto está en `docs/project-context.md`.

## Global Constraints

- Idioma de trabajo, código, comentarios y commits: español rioplatense (voseo en los textos del DJ). Commits en español, rama `main`, git solo local, terminando con `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- No hay ffmpeg. Nada fijo en el código: todo valor que se pueda querer cambiar vive en `ConfigDJ` con un valor por defecto.
- `Pedido.posicion` es opcional y vale `"inicio"` si falta; con `inicio` el texto y la temporización salen como hasta ahora.
- Valores por defecto: `posicion_voz = "mixto"` (las tres con igual probabilidad), `fraccion_entre` 0,3 a 0,7, `final_antes_segundos` 0 a 2, `retraso_voz_segundos` sigue valiendo para `inicio`.
- Cada oración de plantilla tiene al menos cuatro palabras. Cada clase de marcos (*ahora*, *neutra*, *adelante*) tiene al menos tres por idioma, también en los marcos de petición, y toda unión de clases que se use tiene marcos que terminan en `"artista"` y en `"titulo"` (si no, la cola de dato deja un pozo vacío).
- Crossfade, control por CLI/applet y pesos de `mixto` están fuera de alcance.

## Review Focus

1. **Saltear el tema de origen con la voz pendiente:** la voz no sale a destiempo (Task 9).
2. **Sintonizar en el tema de origen, ya cerca del corte:** sale en su momento o entra a mitad de frase, sin repetirse (Task 9).
3. **Tema de origen más corto que el adelanto:** el adelanto se acota a la mitad de su duración (Task 7).
4. **Pozo vacío en un pool de marcos** al filtrar por cola de dato (clase × idioma × petición): `IndexError` en `azar.choice` (Task 3).
5. **Dos intervenciones seguidas** que arman temporizadores en el mismo arranque de tema: no se pisan ni se pierde ninguna (Task 9).

---

### Task 0: Dar de alta la tarea en Beans

- [ ] **Step 1:** Ejecutar `/beans:create` con la descripción "La voz del DJ habla sobre el empalme entre dos temas (posiciones inicio, entre, final y mixto; textos adaptados)", enlazando el diseño. Anotar el id (`CASSETTE-FM-xxxx`) y usarlo en los mensajes de commit de las tareas siguientes.

### Task 1: Posiciones y configuración

**Files:**
- Create: `src/cassette_fm/posiciones.py`
- Modify: `src/cassette_fm/config.py` (`ConfigDJ`, `campos_dj`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `cassette_fm.posiciones.POSICIONES = ("inicio", "entre", "final")`; campos de `ConfigDJ`: `posicion_voz: str = "mixto"`, `fraccion_entre_min: float = 0.3`, `fraccion_entre_max: float = 0.7`, `final_antes_min_segundos: float = 0.0`, `final_antes_max_segundos: float = 2.0`.

- [ ] **Step 1: Escribir las pruebas que fallan** en `tests/test_config.py`:
  - `test_dj_posicion_por_defecto`: `ConfigDJ()` tiene `posicion_voz == "mixto"`, `(fraccion_entre_min, fraccion_entre_max) == (0.3, 0.7)`, `(final_antes_min_segundos, final_antes_max_segundos) == (0.0, 2.0)`.
  - `test_dj_lee_posicion_general_y_por_estacion` (con el patrón de `test_dj_por_estacion_pisa_a_la_general`): `[dj] posicion_voz = "entre"` y `[dj.estaciones."Lentos"] posicion_voz = "final"` dan `entre` general y `final` en Lentos; un `fraccion_entre_min = 0.4` por emisora pisa solo ese campo.
  - Casos nuevos en la lista parametrizada de `test_dj_invalido_da_error_claro`: `'[dj]\nposicion_voz = "medio"'`, `"[dj]\nposicion_voz = 3"`, `"[dj]\nfraccion_entre_min = 1.5"`, `"[dj]\nfraccion_entre_min = 0.8\nfraccion_entre_max = 0.2"`, `"[dj]\nfinal_antes_min_segundos = 5\nfinal_antes_max_segundos = 1"`, `"[dj]\nfinal_antes_min_segundos = -1"`.
  - `test_dj_posicion_por_emisora_en_estaciones_json`: una emisora con `"dj": {"posicion_voz": "final"}` en `estaciones.json` llega a su `ConfigDJ` (mirar cómo lo hacen los tests de `tests/test_emisoras.py` para `velocidad`).
- [ ] **Step 2:** Correr `python3 -m pytest tests/test_config.py tests/test_emisoras.py -q`. Esperado: FALLAN las nuevas.
- [ ] **Step 3: Implementar.** Crear `posiciones.py` con la constante. Agregar los campos a `ConfigDJ` (los `float` ya se leen solos por `_CAMPOS_NUMERICOS_DJ`, con la regla de "no negativo"). En `campos_dj`: rama `posicion_voz` (texto en `("mixto", *POSICIONES)`, si no `ErrorConfig` con el archivo y la lista de valores); rama o chequeo posterior para `fraccion_entre_*` (entre 0 y 1) y para los pares `min ≤ max`, con el mismo estilo que el chequeo de `espera_reintento_*` al final de la función (se evalúa sobre `replace(base, **campos)`).
- [ ] **Step 4:** Correr `python3 -m pytest tests/test_config.py tests/test_emisoras.py tests/test_cli.py -q`. Esperado: todo en verde.
- [ ] **Step 5: Commit** — `git add src/cassette_fm/posiciones.py src/cassette_fm/config.py tests/test_config.py && git commit -m "DJ: configuración de la posición de la voz (posicion_voz, fracciones y márgenes)"`.

### Task 2: El pedido al servicio DJ lleva la posición

**Files:**
- Modify: `src/cassette_fm/dj/pedido.py` (`Pedido`, `leer_pedido`)
- Test: `tests/dj/test_pedido.py`

**Interfaces:**
- Consumes: `POSICIONES` de `cassette_fm.posiciones`.
- Produces: `Pedido.posicion: str = "inicio"` (último campo del dataclass, con valor por defecto).

- [ ] **Step 1: Pruebas que fallan** en `tests/dj/test_pedido.py`: `leer_pedido(pedido_valido()).posicion == "inicio"`; con `"posicion": "entre"` y `"final"` se lee tal cual; `"posicion": "medio"`, `5` y `"ENTRE"` lanzan `ValueError` cuyo mensaje contiene `campo 'posicion'`; `None` explícito equivale a `"inicio"`.
- [ ] **Step 2:** Correr `python3 -m pytest tests/dj/test_pedido.py -q`. Esperado: FALLAN.
- [ ] **Step 3: Implementar** `Pedido.posicion` y la validación en `leer_pedido` (mensaje: `campo 'posicion': tiene que ser inicio, entre o final`).
- [ ] **Step 4:** Correr `python3 -m pytest tests/dj -q`. Esperado: verde (`tests/dj/test_sin_extra.py` incluido: el módulo no puede importar nada pesado).
- [ ] **Step 5: Commit** — `DJ: el pedido acepta la posición de la voz (inicio, entre, final)`.

### Task 3: Marcos de plantilla clasificados por clase

**Files:**
- Modify: `src/cassette_fm/dj/plantillas.py` (`_MARCOS`, `_MARCOS_PETICION`, nuevo `marcos_para`, uso en `redactar`)
- Test: `tests/dj/test_plantillas.py`

**Interfaces:**
- Produces:
  - `_MARCOS: dict[str, dict[str, list[tuple[str, str | None]]]]`, indexado `[idioma][clase]` con clases `"ahora"`, `"neutra"`, `"adelante"` (cada marco: `(texto, nombre_con_el_que_termina)` como hoy).
  - `_MARCOS_PETICION: dict[str, dict[str, dict[str, list[...]]]]`, indexado `[idioma][modo][clase]` con `modo` en `"antes"`, `"seguidas"`.
  - `marcos_para(idioma: str, posicion: str, peticion: str | None) -> list[tuple[str, str | None]]`: `inicio` → clases `ahora`+`neutra`; `entre` → `neutra`; `final` → `adelante`+`neutra`. Con `peticion` en `"antes"`/`"seguidas"` usa `_MARCOS_PETICION`; con cualquier otro valor, `_MARCOS`.
- Clasificación de los marcos que existen (spec, sección Textos): **es** *ahora* = "Ahora suena…", "De {artista} escuchamos ahora…"; *neutra* = los otros seis; **en** *ahora* = "Now playing…"; *adelante* = los tres "Coming up next…"/"Up next is…"; *neutra* = "Here comes…" ×2 y "Stay with us for…". Marcos de petición: *ahora* = los que dicen "suena" ("Por pedido… suena…", "…ahora suena…"); *neutra* = el resto de "llega"/"tenemos"/"here is".

- [ ] **Step 1: Pruebas que fallan** en `tests/dj/test_plantillas.py`:
  - `test_cada_clase_tiene_al_menos_tres_marcos` (parametrizada por idioma, y por `None`/`"antes"`/`"seguidas"`): cada una de las tres clases tiene `len >= 3`.
  - `test_toda_union_de_clases_tiene_cola_de_artista_y_de_titulo`: para cada idioma, posición y petición, `{nombre for _, nombre in marcos_para(...)}` incluye `"artista"` y `"titulo"`.
  - `test_las_clases_por_posicion` (con `monkeypatch.setattr(plantillas, "_MARCOS", ...)` poniendo marcos centinela `"AHORA suena {titulo} de {artista}"`, `"NEUTRA llega {titulo} de {artista}"`, `"ADELANTE sigue {titulo} con {artista}"` con ambos finales para cada clase): sobre 200 semillas, `redactar` con `Pedido(posicion="inicio")` nunca dice `ADELANTE`, con `"entre"` solo `NEUTRA`, con `"final"` nunca `AHORA`; y cada una de las permitidas aparece al menos una vez en `inicio` y `final`.
  - Lo mismo para marcos de petición (`peticion="antes"` y `"seguidas"`) monkeypatcheando `_MARCOS_PETICION`.
  - Con una cola de dato elegida (hechos con año o país, pesos que fuerzan `"dato"`), ninguna combinación de posición × idioma × petición lanza excepción en 100 semillas.
- [ ] **Step 2:** Correr `python3 -m pytest tests/dj/test_plantillas.py -q`. Esperado: FALLAN.
- [ ] **Step 3: Implementar.** Reestructurar `_MARCOS` y `_MARCOS_PETICION` con la clasificación de arriba; agregar frases hasta cumplir "≥ 3 por clase e idioma" (en español: *adelante* "A continuación…", "Enseguida…", "Más adelante…"/"Ya viene…", además de una *ahora* nueva; en inglés: más *ahora*; en petición: *adelante* y *ahora* que falten). Español rioplatense, cada oración con ≥ 4 palabras. Escribir `marcos_para` y usarla en `redactar` (por ahora con `posicion` leída de `pedido.posicion`; el resto de `redactar` no cambia). Reemplazar el uso directo de `_MARCOS[idioma]`/`_MARCOS_PETICION[idioma][peticion]` y el fallback del final (`min(... marcos ...)`).
- [ ] **Step 4:** Correr `python3 -m pytest tests/dj -q`. Esperado: verde, incluyendo `test_invariantes_de_todas_las_*` y `test_la_variedad_en_cientos_de_pedidos`.
- [ ] **Step 5: Commit** — `DJ: marcos de plantilla clasificados (ahora, neutra, adelante) y elegidos según la posición`.

### Task 4: Cierre del anterior y frases en presente según la posición

**Files:**
- Modify: `src/cassette_fm/dj/plantillas.py` (`_EXTRAS`, `_PETICION_ANTERIOR`, `redactar`)
- Test: `tests/dj/test_plantillas.py`

**Interfaces:**
- Consumes: `marcos_para`, `Pedido.posicion`.
- Produces: `_EXTRAS[idioma]["anterior_en_curso"]` (lista de frases en presente que nombran `{titulo_ant}` y `{artista_ant}`: "Está terminando…", "Estás escuchando…" / "That is…"; ≥ 3 por idioma) y `_PETICION_ANTERIOR_EN_CURSO[idioma]` (≥ 3: "Termina {titulo_ant} de {artista_ant}, un pedido especial del público"). Siguen existiendo `_EXTRAS[idioma]["anterior"]` y `_PETICION_ANTERIOR` (pasado).

Reglas en `redactar` (spec, "Reglas por posición"):
- `inicio`: igual que hoy.
- `entre` con anterior con nombre y sin petición "después"/"seguidas": el cierre (`_EXTRAS[idioma]["anterior"]`) es el **prefijo** fijo (mecanismo de `prefijo`: va primero, nunca se descarta) y el ingrediente `"anterior"` sale de `disponibles`. Con "después"/"seguidas" el prefijo ya es `_PETICION_ANTERIOR` (pasado). Sin anterior: sin cierre.
- `final`: el ingrediente `"anterior"` (opcional, como hoy) usa `anterior_en_curso`; el prefijo de "después"/"seguidas" usa `_PETICION_ANTERIOR_EN_CURSO`.

- [ ] **Step 1: Pruebas que fallan** (monkeypatcheando `_EXTRAS`/`_PETICION_ANTERIOR*` con centinelas de ≥ 4 palabras, p. ej. `"CIERRE de {artista_ant} con {titulo_ant} ya listo."`, `"ENCURSO suena {titulo_ant} de {artista_ant} todavía."`):
  - `entre` con anterior: `redactar(...).marcado.startswith("CIERRE")` en 100 semillas; sin anterior: nunca contiene `CIERRE`.
  - `final`: nunca `CIERRE`; con pesos que fuerzan `"anterior"` aparece `ENCURSO`.
  - `inicio`: sin `ENCURSO`; compatible con lo de hoy (el ingrediente `"anterior"` sigue usando `anterior`).
  - Petición "despues" y "seguidas": `inicio`/`entre` usan `_PETICION_ANTERIOR`, `final` usa `_PETICION_ANTERIOR_EN_CURSO` (centinelas `PEDIDO-PASADO` y `PEDIDO-ENCURSO`).
  - `entre` con anterior respeta `palabras_maximas` (el cierre cuenta y no se descarta; se sacan los demás ingredientes primero).
  - Pruebas de invariantes existentes (`test_invariantes_de_todas_las_combinaciones`) parametrizadas también por `posicion` ∈ `POSICIONES`: sin dígitos, sin llaves sin resolver, cada oración con ≥ 4 palabras.
- [ ] **Step 2:** Correr `python3 -m pytest tests/dj/test_plantillas.py -q`. Esperado: FALLAN.
- [ ] **Step 3: Implementar** las listas nuevas y las reglas en `redactar`.
- [ ] **Step 4:** Correr `python3 -m pytest tests/dj -q`. Esperado: verde.
- [ ] **Step 5: Commit** — `DJ: las plantillas cierran el tema anterior en "entre" y hablan en presente en "final"`.

### Task 5: El LLM recibe la posición

**Files:**
- Modify: `src/cassette_fm/dj/redactor_llm.py` (`construir_peticion`, `verificar`)
- Test: `tests/dj/test_redactor_llm.py`

**Interfaces:**
- Consumes: `Pedido.posicion`.
- Produces: en `construir_peticion`, una línea más en `Peticion.usuario` por posición (textos exactos):
  - es/`entre`: `"Empezás a hablar mientras termina el tema anterior y terminás con el tema nuevo ya sonando: cerrá el anterior y presentá el siguiente."`
  - es/`final`: `"Hablás antes de que empiece el tema nuevo: usá futuro (a continuación, enseguida) y no digas que ya suena."`
  - en/`entre`: `"You start talking while the previous song is ending and finish with the new song already playing: close the previous one and introduce the next one."`
  - en/`final`: `"You speak before the new song starts: use the future (up next, coming up) and do not say it is already playing."`
  - Con `entre` y anterior, la línea `Tema anterior: …` va siempre (aunque `"anterior"` no esté en los ingredientes). `inicio`: igual que hoy.
  - `verificar`: con `posicion == "entre"` y `pedido.anterior` no nulo, si el texto no nombra el título del anterior (normalizado como el del siguiente) devuelve `"no nombra el tema anterior"`. En `inicio` y `final` no cambia nada.

- [ ] **Step 1: Pruebas que fallan** en `tests/dj/test_redactor_llm.py`: (a) `construir_peticion` con `posicion="inicio"` es idéntico al de un pedido sin posición; (b) con `"entre"` el `usuario` contiene `mientras termina el tema anterior` (es) / `while the previous song is ending` (en) y `Tema anterior:` / `Previous song:` aunque `ingredientes=()`; (c) con `"final"` contiene `antes de que empiece el tema nuevo` / `before the new song starts`; (d) `verificar` devuelve `"no nombra el tema anterior"` en `entre` si falta y `None` si está, y no pide nada en `inicio` ni `final`.
- [ ] **Step 2:** Correr `python3 -m pytest tests/dj/test_redactor_llm.py -q`. Esperado: FALLAN.
- [ ] **Step 3: Implementar** las líneas y el chequeo.
- [ ] **Step 4:** Correr `python3 -m pytest tests/dj -q`. Esperado: verde.
- [ ] **Step 5: Commit** — `DJ: el prompt del LLM y su verificación entienden la posición de la voz`.

### Task 6: La intervención recuerda su corte, su origen y su posición

**Files:**
- Modify: `src/cassette_fm/intervenciones.py` (`Intervencion`, `_cargar`)
- Test: `tests/test_intervenciones.py`

**Interfaces:**
- Produces: campos nuevos al final de `Intervencion`: `corte: float | None = None`, `pista_origen: str | None = None`, `posicion: str = "inicio"`; método `corte_estimado(self, retraso_voz: float) -> float` que devuelve `corte` si existe, si no `inicio - retraso_voz`.

- [ ] **Step 1: Pruebas que fallan** en `tests/test_intervenciones.py`: ida y vuelta por el JSON con los tres campos; un JSON sin ellos carga con `corte is None`, `pista_origen is None`, `posicion == "inicio"`; una `posicion` inválida en el JSON carga como `"inicio"`; `corte_estimado(1.0)` con y sin `corte`; `activa()`/`limpiar()`/solape no cambian con los campos nuevos.
- [ ] **Step 2:** Correr `python3 -m pytest tests/test_intervenciones.py -q`. Esperado: FALLAN.
- [ ] **Step 3: Implementar** los campos (con `asdict` ya se guardan) y la lectura tolerante en `_cargar`.
- [ ] **Step 4:** Correr `python3 -m pytest tests/test_intervenciones.py tests/test_locutor.py tests/test_planificador.py -q`. Esperado: verde (los defaults no rompen a los constructores existentes).
- [ ] **Step 5: Commit** — `La intervención guarda el corte, el tema de origen y la posición de la voz`.

### Task 7: Sorteo de la posición e inicio real de la voz (funciones puras)

**Files:**
- Modify: `src/cassette_fm/planificacion.py` (`Hueco`, `elegir_hueco`, `armar_pedido`, dos funciones nuevas)
- Test: `tests/test_planificacion.py`

**Interfaces:**
- Consumes: `POSICIONES`, campos nuevos de `ConfigDJ`.
- Produces:
  - `Hueco` suma al final `posicion: str = "inicio"` y `origen: Pista | None = None`. `inicio_tema` **es el corte**; `inicio_voz` queda como el instante nominal `inicio_tema + retraso_voz_segundos` (lo usan el `momento` del pedido y el chequeo de "llegó tarde").
  - `sortear_posicion(cfg: ConfigDJ, azar: random.Random, margen_disponible: float | None = None) -> str`: `mixto` → `azar.choice(POSICIONES)`; cualquier otro valor de `cfg.posicion_voz` → ese. Si `margen_disponible` no es `None` y es menor que `cfg.peticion_margen_segundos + cfg.duracion_maxima_segundos`, devuelve `"inicio"`.
  - `inicio_de_la_voz(posicion: str, corte: float, duracion: float, cfg: ConfigDJ, azar: random.Random, duracion_origen: float | None = None) -> float`: `inicio` → `corte + cfg.retraso_voz_segundos`; `entre` → `corte - f*duracion` con `f = azar.uniform(fraccion_entre_min, fraccion_entre_max)`; `final` → `corte - m - duracion` con `m = azar.uniform(final_antes_min_segundos, final_antes_max_segundos)`; si `duracion_origen` no es `None` el inicio no puede ser anterior a `corte - duracion_origen/2`.
  - `elegir_hueco` devuelve `Hueco(..., posicion=sortear_posicion(cfg, azar), origen=anterior)` (el sorteo va **después** de elegir el tema para no alterar el orden de los sorteos existentes) y, al chequear `ocupados`, usa la ventana `[corte - duracion_maxima, corte + retraso + duracion_maxima]`.
  - `armar_pedido` agrega siempre `pedido["posicion"] = hueco.posicion`.

- [ ] **Step 1: Pruebas que fallan** en `tests/test_planificacion.py`:
  - `sortear_posicion`: con `posicion_voz="final"` → `"final"`; con `"mixto"` y 300 sorteos salen las tres, cada una entre 25 % y 42 %; con `margen_disponible=10` → `"inicio"` aunque sea `final`; con `margen_disponible = peticion_margen + duracion_maxima` → no degrada.
  - `inicio_de_la_voz`: `inicio` → `corte + 1.0`; `entre` con `duracion=10`, rango (0,3; 0,7) → `corte - [3, 7]`; `final` con `duracion=10`, margen (0, 2) → `corte - [10, 12]`; con `duracion_origen=20` y `final` con clip de 25 s → `>= corte - 10` (acotado); con `fraccion_entre` fija (min=max=0,5) → exactamente `corte - 5`.
  - `elegir_hueco` devuelve `posicion` según config y `origen == anterior`; el ejemplo de determinismo con la misma semilla sigue valiendo; un hueco con `posicion_voz="entre"` y un `ocupados` que cae justo antes del corte lo descarta.
  - `armar_pedido(...)["posicion"]` es la del hueco y el pedido sigue pasando `leer_pedido`.
- [ ] **Step 2:** Correr `python3 -m pytest tests/test_planificacion.py -q`. Esperado: FALLAN.
- [ ] **Step 3: Implementar** según las firmas.
- [ ] **Step 4:** Correr `python3 -m pytest tests/test_planificacion.py tests/dj -q`. Esperado: verde.
- [ ] **Step 5: Commit** — `Planificación: sorteo de la posición de la voz y cálculo de su inicio real`.

### Task 8: El planificador usa el corte y la posición

**Files:**
- Modify: `src/cassette_fm/planificador.py` (`_Trabajo`, `_Peticion`, `_iniciar`, `pedir_ahora`, `_iniciar_peticion`, `_recibir`, `_antes_reservado`, `_olvidar_anuncios`, `al_cambiar_agenda`, `al_encolado`, `_cargar`)
- Test: `tests/test_planificador.py`

**Interfaces:**
- Consumes: `sortear_posicion`, `inicio_de_la_voz`, `Hueco.posicion/origen`, `Intervencion.corte/pista_origen/posicion`, `Intervencion.corte_estimado`.
- Produces: `_Trabajo` suma `pista_origen: str | None = None`, `duracion_origen: float | None = None`, `posicion: str = "inicio"` (se persisten solos con `vars()`; `_cargar` los lee con `.get` y una `posicion` inválida cae a `"inicio"`); `_Peticion` suma `origen: Pista | None = None`.

Comportamiento:
- Los cuatro lugares que crean un `_Trabajo` (`_iniciar`, `pedir_ahora`, `_iniciar_peticion`, y su lectura) pasan origen, su duración y la posición del hueco. Hay que factorizar la creación en un solo método.
- `_iniciar_peticion`: arma el `Hueco` con `posicion = sortear_posicion(cfg, azar, margen_disponible=p.inicio_tema - ahora)` si `p.modo == "antes"`, y sin margen (`None`) si es `"despues"`; `origen = p.origen`. `al_encolado` pasa `origen=anterior` (el tema actual, aunque no tenga nombre) y `al_cambiar_agenda` pasa `origen=nuevo.pista`.
- `_recibir`: `inicio = inicio_de_la_voz(t.posicion, t.inicio_tema, duracion, cfg, self._azar, t.duracion_origen)`. En `entre` y `final`, si `inicio < reloj + 1` se descarta (borra el audio, log, `_trabajo = None`, espera creciente como cuando falla el registro). Se registra `Intervencion(..., inicio, ..., corte=t.inicio_tema, pista_origen=t.pista_origen, posicion=t.posicion)` y `Ultima(t.inicio_tema, inicio + duracion)`.
- `_antes_reservado`, `_olvidar_anuncios` y `al_cambiar_agenda` reemplazan `i.inicio - retraso` por `i.corte_estimado(retraso)`.
- La comprobación "llegó tarde" de `_avanzar` no cambia (usa el instante nominal).

- [ ] **Step 1: Pruebas que fallan** en `tests/test_planificador.py`. Primero: los `CFG` de ese archivo pasan a `posicion_voz="inicio"` para que las pruebas existentes mantengan su sentido. Nuevas (con `replace(CFG, posicion_voz=...)`, `random.Random` con semilla fija y el `ClienteFalso`/`LocutorFalso` del archivo):
  - el pedido enviado lleva `posicion`, y el trabajo persistido (`_guardar`/recarga en un `Planificador` nuevo) conserva `pista_origen`, `duracion_origen` y `posicion`;
  - `final` con clip de 3 s: la `Intervencion` registrada tiene `inicio == corte - m - 3.0` con `m` en `[0, 2]`, `corte == hueco.inicio_tema`, `pista_origen == clave del anterior`, `posicion == "final"`; `Ultima.fin == inicio + 3.0`;
  - `entre`: `corte - 0.7*3 <= inicio <= corte - 0.3*3`;
  - `entre`/`final` cuyo inicio ya pasó (reloj adelantado hasta después del inicio calculado): no se registra, el audio descargado se borra y no queda trabajo en curso;
  - `inicio` con el reloj pasado del inicio calculado: sigue registrando (como hoy);
  - petición "antes" con `corte - ahora` justo por debajo de `peticion_margen + duracion_maxima` → `posicion == "inicio"` aunque `posicion_voz="final"`; "después" → respeta `posicion_voz`;
  - `_antes_reservado` y `al_cambiar_agenda` reconocen un "antes" reservado en `final` (con `inicio` muy anterior al corte) y no lo duplican;
  - un estado guardado sin los campos nuevos se carga (como `inicio`).
- [ ] **Step 2:** Correr `python3 -m pytest tests/test_planificador.py -q`. Esperado: FALLAN las nuevas; las viejas siguen en verde.
- [ ] **Step 3: Implementar** según el comportamiento de arriba.
- [ ] **Step 4:** Correr `python3 -m pytest tests/test_planificador.py tests/test_planificacion.py tests/test_servicio.py -q`. Esperado: verde.
- [ ] **Step 5: Commit** — `Planificador: la voz se reserva alrededor del corte según su posición`.

### Task 9: El locutor dispara la voz desde el tema de origen

**Files:**
- Modify: `src/cassette_fm/locutor.py` (`pista_iniciada`, `registrar`, `al_sintonizar`, `descartar_estacion`, `detener`, anclajes)
- Test: `tests/test_locutor.py`

**Interfaces:**
- Consumes: `Intervencion.corte_estimado`, `.pista_origen`, `.posicion`.
- Produces: `Locutor.pista_iniciada(self, pista: Pista, estacion: str, desfase: float = 0.0) -> None`. `desfase` es el medido en ese arranque (`agenda.desfase`; 0 si no se conoce).

Comportamiento (spec, "El locutor"):
- Los anclajes pasan de uno solo (`_t_anclaje`/`_anclada`/`_estacion_anclaje`) a una **lista** de `(timer, intervención)`, y `descartar_estacion`, `al_sintonizar` y `detener` los cancelan (salvo, en `descartar_estacion`, los de peticiones, como hoy).
- Al empezar cualquier tema de la estación sintonizada, primero se cancelan todos los anclajes pendientes; después se arman los que corresponden.
- Para cada candidata no reproducida: sea `corte = i.corte_estimado(cfg.retraso_voz_segundos)`.
  - Si `i.inicio >= corte` y `pista.clave == i.pista_destino`: igual que hoy (se exige `|ahora - corte| <= tolerancia_desfase_segundos`), espera `i.inicio - corte`.
  - Si `i.inicio < corte` y `pista.clave == i.pista_origen`: espera `i.inicio - (ahora - desfase)`; se arma solo si `0 <= espera <= pista.duracion + tolerancia_desfase_segundos`.
- `registrar`: si la voz empieza antes del corte, su origen es el tema que suena ahora (el locutor recuerda la clave y el desfase del tema actual) y `i.inicio` todavía no llegó, arma el temporizador con espera `i.inicio - (ahora - desfase_actual)`; si la ventana ya está abierta entra a mitad de frase, como hoy.
- Todo lo demás (ducking, volumen 0, `minimo_restante_segundos`, seguridad) sin cambios.

- [ ] **Step 1: Pruebas que fallan** en `tests/test_locutor.py`. El helper `mundo.iv` suma parámetros `corte=None, origen=None, posicion="inicio"`. Con el `CFG` de ahí (retraso 0,05 s) y los temporizadores reales (`esperar`):
  - `test_la_voz_final_se_ancla_al_tema_de_origen`: `registrar(iv(T0+0.3, corte=T0+0.8, origen="/m/o.mp3", destino="/m/d.mp3", posicion="final"))` y `pista_iniciada(Pista(Path("/m/o.mp3"), 1.0, "o"), "E", 0.0)`: no hay carga antes de ~0,15 s y hay una carga con `start ≈ 0` en menos de 1,5 s.
  - `test_el_desfase_corre_la_voz`: con `desfase=0.3` la voz sale ~0,3 s más tarde (cota inferior 0,45 s después del arranque, carga antes de 1,5 s).
  - `test_saltear_el_origen_cancela_la_voz_pendiente` (**Review Focus 1**): se arma por el origen con espera ~0,5 s y `pista_iniciada` de **otro** tema antes de que salte; tras 0,8 s no hay cargas.
  - `test_sintonizar_en_el_origen_cerca_del_corte` (**Review Focus 2**): `al_sintonizar`, reloj en `T0+0.1`, voz con `inicio=T0+0.3`, arranque del origen alineado (`desfase=0`) → sale en ~0,2 s y una segunda `pista_iniciada` del mismo tema no la repite; con el reloj ya dentro de la ventana, entra a mitad de frase (`start > 0`) y el arranque del origen no la repite.
  - `test_origen_que_no_alcanza_para_el_adelanto_no_dispara`: `espera > pista.duracion + tolerancia` → no carga.
  - `test_dos_intervenciones_seguidas_arman_dos_temporizadores` (**Review Focus 5**): X de `inicio` (destino `/m/t.mp3`, `corte=T0`, `inicio=T0+0.05`, clip de 0,2 s) e Y de `final` (origen `/m/t.mp3`, `corte=T0+0.9`, `inicio=T0+0.5`) con un solo `pista_iniciada(t)`: suena X (se simula su fin con `mundo.voz.fin()`) y después Y.
  - `test_registrar_con_el_origen_sonando_arma_por_reloj`: `pista_iniciada(origen)` primero, `registrar(iv final)` después, con `inicio` futuro: sale a su hora.
  - `test_descartar_estacion_y_detener_cancelan_los_anclajes_de_origen`; `test_las_peticiones_no_se_desanclan_al_descartar` sigue valiendo para anclajes de origen.
  - Las pruebas viejas de anclaje por destino no se tocan y pasan.
- [ ] **Step 2:** Correr `python3 -m pytest tests/test_locutor.py -q`. Esperado: FALLAN las nuevas.
- [ ] **Step 3: Implementar** los anclajes múltiples y la nueva lógica.
- [ ] **Step 4:** Correr `python3 -m pytest tests/test_locutor.py tests/test_radio.py -q`. Esperado: verde.
- [ ] **Step 5: Commit** — `Locutor: la voz de "entre" y "final" se dispara desde el arranque del tema de origen`.

### Task 10: La radio le pasa el desfase al locutor

**Files:**
- Modify: `src/cassette_fm/radio.py` (`_al_cambiar_pista`, `_medir_desfase`)
- Test: `tests/test_radio.py` (incluye el `LocutorFalso`, línea ~452)

**Interfaces:**
- Consumes: `Locutor.pista_iniciada(pista, estacion, desfase)`.
- Produces: `_medir_desfase(pista, estacion) -> float` devuelve el desfase medido, o `0.0` para el primer tema tras sintonizar y si `agenda.desfase` da `None`; `_al_cambiar_pista` llama a `self._dj.pista_iniciada(pista, estacion.nombre, desfase)` con ese valor.

- [ ] **Step 1: Pruebas que fallan**: el `LocutorFalso.pista_iniciada(self, pista, nombre, desfase=0.0)` registra `("pista_iniciada", pista, nombre, desfase)`; nuevas: el primer arranque tras sintonizar pasa `0.0`; un segundo arranque con la música 2 s atrasada respecto del reloj pasa `≈ 2.0`; un tema que no es ni el actual ni el siguiente de la agenda pasa `0.0`. Actualizar las pruebas existentes que comparan la tupla vieja.
- [ ] **Step 2:** Correr `python3 -m pytest tests/test_radio.py -q`. Esperado: FALLAN.
- [ ] **Step 3: Implementar** (la medición tiene que ocurrir antes de avisar al locutor; el aviso por log de `desfase_aviso_segundos` sigue igual).
- [ ] **Step 4:** Correr la suite completa: `python3 -m pytest -q` (≈ 2,5 min). Esperado: todo en verde, sin regresiones.
- [ ] **Step 5: Commit** — `Radio: el locutor recibe el desfase medido en cada arranque de tema`.

### Task 11: Documentación y prueba real

**Files:**
- Modify: `docs/project-context.md` (un párrafo en "Estado"), `README.md` si documenta la configuración del DJ (buscar `retraso_voz` o `frecuencia`).
- Modify: el bean de la Task 0 (cerrarlo al terminar).

- [ ] **Step 1:** Agregar a `docs/project-context.md`, junto a los demás hitos, un párrafo con enlace al diseño y al plan: la voz del DJ se ancla al corte entre temas (`posicion_voz`: `inicio`, `entre`, `final`, `mixto`). Documentar `posicion_voz` y los rangos en el README donde estén los ajustes del DJ.
- [ ] **Step 2: Prueba real con el usuario** (no se marca como hecha sin su OK): reiniciar los servicios (`systemctl --user restart cassette-fm cassette-dj`; **nunca** `systemctl status` ni `ps` con argumentos sobre Soloist), con la configuración de prueba actual (una intervención por tema). Escuchar una emisora local y una de Spotify con `posicion_voz` = `inicio`, `entre`, `final` y `mixto`; verificar de oído: nunca "ahora suena" sobre el tema anterior, el cierre en `entre`, futuro en `final`, y que una petición encolada se anuncia bien.
- [ ] **Step 3:** Si algo suena mal, anotar qué posición y qué emisora y volver a la tarea que corresponda; si todo está bien, completar el bean.
- [ ] **Step 4: Commit** — `Documentación de la voz del DJ entre temas` (incluye este plan y el diseño si todavía no están commiteados).
