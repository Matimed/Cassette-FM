# Cierre de las peticiones Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anuncio combinado de dos pedidos seguidos y los cinco casos menores de la cola de la etapa 7a.

**Architecture:** El servicio DJ suma el modo de petición `seguidas`; el planificador lo pide cuando el tema actual es
un pedido y descarta los anuncios que ya no van a sonar (tema sacado de la cola, pedido salteado); el reproductor de
Spotify avisa cuándo un encolado se sacó de la cola; la radio toma del reproductor solo corrimiento y pedidos.

**Tech Stack:** Python 3, pytest (`.venv/bin/pytest -q -p no:cacheprovider`).

**Spec:** `docs/superpowers/specs/2026-11-15-peticiones-cierre-design.md` (parte de
`docs/superpowers/specs/2026-11-15-peticiones-spotify-design.md`).

## Global Constraints

- Commits en español, imperativo llano, terminados en `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; git
  solo local en `main`.
- Los tests nunca tocan el bus de sesión real ni el Soloist real.
- El modo nuevo se llama `seguidas` en el pedido HTTP del servicio DJ y requiere `anterior` (como `despues`).
- Las intervenciones reservadas siguen guardando `peticion` = `"antes"`/`"despues"` (un `seguidas` se guarda como
  `"antes"`: se ancla al comienzo del segundo pedido).

## Review Focus

1. El `queue_changed` transitorio con `spotify:meta:node_rules_placeholder` (aparece al agregar a la cola) no debe
   contar como "sacaron el encolado" ni vaciar la cola conocida.
2. Un pedido que termina normalmente (no salteado) conserva su «después» aunque el tema siguiente empiece 1–2 s corrido.
3. Tras un reinicio, la cola reenviada no debe disparar descartes espurios de anuncios ya reservados.
4. `seguidas` sin `anterior` (pedido HTTP mal armado) da error claro, no un anuncio que nombra "None".
5. El rescan que llega mientras empieza un pedido no pierde el pedido ni las pistas nuevas.

---

### Task 1: Modo `seguidas` en el servicio DJ

**Files:**
- Modify: `src/cassette_fm/dj/pedido.py` (validación de `peticion`), `src/cassette_fm/dj/plantillas.py` (`_PETICION`,
  elección de `peticion`), `src/cassette_fm/dj/redactor_llm.py` (`construir_peticion`)
- Test: `tests/dj/test_pedido.py`, `tests/dj/test_plantillas.py`, `tests/dj/test_redactor_llm.py`

**Interfaces:**
- Produces: `Pedido.peticion in (None, "antes", "despues", "seguidas")`; `leer_pedido` exige `anterior` para
  `despues` y `seguidas`.

- [ ] **Step 1: Tests que fallan**

```python
# tests/dj/test_pedido.py — ampliar los existentes
def test_peticion_valida_y_opcional():          # el for pasa a ("antes", "despues", "seguidas")
def test_peticion_invalida_da_error():          # mensaje: "campo 'peticion': tiene que ser antes, despues o seguidas"
def test_seguidas_sin_anterior_da_error():
    d = pedido_valido(); d["peticion"] = "seguidas"; del d["anterior"]
    with pytest.raises(ValueError, match=r"campo 'anterior': falta \(peticion seguidas\)"):
        leer_pedido(d)

# tests/dj/test_plantillas.py
@pytest.mark.parametrize("idioma,inicio,otra", [
    ("es", "Eso fue una petición especial: Is This Love de Whitesnake.", "Y llega otra."),
    ("en", "That was a special request: Is This Love by Whitesnake.", "And here comes another one.")])
def test_plantilla_seguidas_cierra_el_pedido_anterior_y_abre_el_siguiente(idioma, inicio, otra):
    p = _replace(pedido(idioma=idioma), peticion="seguidas")
    for semilla in range(20):
        r = redactar(p, Lexico(), random.Random(semilla), 45, zona=ZONA)
        texto = MARCA.sub(lambda m: m.group(2), r.marcado)
        assert texto.startswith(f"{inicio} {otra}"), texto
        assert texto.count("Whitesnake") == 1 and "Waiting for a Girl Like You" in texto

# tests/dj/test_redactor_llm.py — dos casos más en test_prompt_llm_marca_la_peticion
("es", "seguidas", "El tema anterior fue una petición especial del público y este también: mencioná el anterior y "
                   "presentá este como petición."),
("en", "seguidas", "The previous song was a special request from a listener and so is this one: mention the "
                   "previous one and introduce this one as a request."),
# y el `if valor == "despues"` del test pasa a `if valor in ("despues", "seguidas")`
```

- [ ] **Step 2:** `.venv/bin/pytest tests/dj -q -p no:cacheprovider` → FAIL en los tests nuevos.
- [ ] **Step 3: Implementar.** `_PETICION[idioma]["seguidas"]` = el texto de `despues` seguido de la oración «Y llega
  otra.» / «And here comes another one.»; en `redactar`, `seguidas` sin `anterior` cae a `antes` (como `despues` cae a
  nada) y con `anterior` descarta el ingrediente `anterior` (ya lo nombra). En `construir_peticion`, la línea del modo
  es la del test y el tema anterior va siempre (como en `despues`).
- [ ] **Step 4:** `.venv/bin/pytest tests/dj -q -p no:cacheprovider` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Servicio DJ: modo de petición seguidas (el anterior fue un pedido y este también)"`

### Task 2: El planificador pide `seguidas` y descarta anuncios que no van a sonar

**Files:**
- Modify: `src/cassette_fm/planificador.py` (`_Peticion`, `al_encolado`, `al_cambiar_agenda`, `_iniciar_peticion`,
  nuevo `al_desencolado`)
- Test: `tests/test_planificador.py` (fixture `con_peticiones`)

**Interfaces:**
- Consumes: Task 1 (`peticion="seguidas"` en `armar_pedido`).
- Produces: `Planificador.al_desencolado(clave: str) -> None` (la usa Task 3).

- [ ] **Step 1: Tests que fallan**

```python
def test_encolar_mientras_suena_un_pedido_pide_seguidas(con_peticiones):
    # est con un pedido PEDIDO en curso (con_pedido en el borde); al_encolado(OTRO, nueva, fin del pedido) → paso
    # → la petición enviada tiene peticion == "seguidas" y anterior titulo "Bohemian Rhapsody";
    # al reservarla, la intervención guarda peticion == "antes"
def test_encolar_mientras_suena_un_tema_de_la_agenda_pide_antes(con_peticiones):
    # sin pedido en curso: peticion == "antes" (regresión)
def test_sacar_el_encolado_sin_poner_otro_descarta_su_antes(con_peticiones):
    # _registrar_antes(m, est) → m.p.al_desencolado(PEDIDO.clave) → m.registro.todas() == []
    # y volver a encolarlo (al_encolado(PEDIDO, est, fin) + paso) pide un antes nuevo
def test_desencolar_cancela_el_antes_en_preparacion(con_peticiones):
    # al_encolado + paso (enviado, sin listo) → al_desencolado → paso → su id en m.cliente.cancelados
def test_saltear_el_pedido_descarta_su_despues(con_peticiones):
    # pedido encolado tarde → empieza en fin → despues reservado (listo) para el tema siguiente;
    # se saltea a los 10 s: nueva = plegar(nueva_con_pedido, fin + 10); al_cambiar_agenda(nueva, None) → paso
    # → el despues no está en m.registro.todas()
def test_el_despues_de_un_pedido_que_termino_bien_se_queda(con_peticiones):
    # igual, pero plegar en fin + PEDIDO.duracion + 1.5 (Spotify un poco atrasado) → el despues sigue
def test_un_pedido_cancela_el_trabajo_normal_de_otra_emisora(con_peticiones):
    # sintonizada "A": paso inicia un normal de "A" (enviado); al_sintonizar(B) sin cambio de agenda de A…
    # forma simple: dejar m.p._trabajo con estacion "OTRA" no-peticion, encolar en est → paso
    # → el id del trabajo de "OTRA" está en m.cliente.cancelados
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_planificador.py -q -p no:cacheprovider` → FAIL en los nuevos.
- [ ] **Step 3: Implementar.**
  - `_Peticion` suma `seguidas: bool = False`; `al_encolado` lo pone si el tema actual (`anterior`) es un pedido en
    curso de `estacion.pedidos` (misma clave, `inicio <= ahora`). `_iniciar_peticion` manda `peticion="seguidas"`
    cuando lo es; el `_Trabajo` e `Intervencion` siguen con `"antes"`.
  - `al_desencolado(clave)`: con el lock, si `clave` está en `_encolados`, la saca y aplica
    `_olvidar_anuncios("antes", destino == clave)`.
  - `al_cambiar_agenda` con `nuevo is None`: para cada «después» de esa emisora (pendiente, en preparación o
    reservado), si su tema destino no empieza en la agenda nueva dentro de `tolerancia_desfase_segundos` de su
    `inicio_tema`, se olvida (`transiciones(estacion, inicio_tema - tolerancia)` hasta `inicio_tema + tolerancia`).
  - `_iniciar_peticion`: si `self._trabajo` es un normal (no petición) de otra emisora, su id va a `_a_cancelar` antes
    de reemplazarlo.
- [ ] **Step 4:** `.venv/bin/pytest -q -p no:cacheprovider` → PASS (suite completa).
- [ ] **Step 5: Commit** `git commit -m "Planificador: anuncio seguidas, y descarta el antes de lo sacado de la cola y el después de lo salteado"`

### Task 3: Reproductor y radio: tema sacado de la cola, ítem sin nombre, rescan con pedido

**Files:**
- Modify: `src/cassette_fm/reproductor_spotify.py` (`_leer_cola`, `_pista_del_item`, callback `al_desencolado`),
  `src/cassette_fm/reproductores.py` (reenviar `al_desencolado`), `src/cassette_fm/radio.py`
  (`_al_desencolado`, `_al_cambiar_agenda`)
- Test: `tests/test_reproductor_spotify.py`, `tests/test_reproductores.py`, `tests/test_radio.py`

**Interfaces:**
- Consumes: Task 2 (`Planificador.al_desencolado(clave: str)`).
- Produces: `ReproductorSpotify.al_desencolado: Callable[[str], None] | None` (clave del encolado avisado que se sacó
  de la cola sin empezar).

- [ ] **Step 1: Tests que fallan**

```python
# tests/test_reproductor_spotify.py (armar registra r.eventos["desencolados"])
def test_sacar_de_la_cola_el_encolado_avisado_lo_desencola():
    # en_marcha; cola(item(AJENO)) → encolados == 1; evento cola() (vacía) → r.eventos["desencolados"] == [AJENO]
def test_la_cola_transitoria_de_soloist_no_desencola_ni_olvida_la_cola():
    # cola(item(AJENO)); {"type": "queue_changed", "upcoming": [{"source": "context", "item":
    #   {"uri": "spotify:meta:node_rules_placeholder"}}]}; cola(item(AJENO))
    # → desencolados == [] y encolados sigue == 1; reloj al fin y cambio(AJENO) → es pedido
def test_el_pedido_que_empieza_no_cuenta_como_desencolado():
    # cola(item(AJENO)); cambio(AJENO) en el borde; cola() → desencolados == []
def test_item_sin_nombre_es_pedido_sin_cancion():
    # cola(item sin "identity" pero con creators y duración) → al empezar es pedido; pedido.pista.cancion is None
    # y pista.titulo no contiene "spotify:track"

# tests/test_reproductores.py
def test_al_desencolado_llega_desde_spotify():

# tests/test_radio.py
def test_desencolado_llega_al_planificador():
def test_cambio_de_agenda_conserva_las_pistas_de_la_radio():
    # la radio tiene la emisora con pistas nuevas (tras rescan); el reproductor llama al_cambiar_agenda con la misma
    # emisora pero pistas viejas, corrimiento 10 y un pedido → la emisora de la radio queda con las pistas nuevas,
    # corrimiento 10 y ese pedido, y es la que recibe el planificador
```

- [ ] **Step 2:** correr los tres archivos → FAIL en los nuevos.
- [ ] **Step 3: Implementar.** `_leer_cola` ignora entero el evento si algún ítem tiene URI `spotify:meta:…`; si
  `_anunciado` ya no está en la cola nueva, lo devuelve como desencolado (y `_anunciado = None`); `manejar_evento`
  llama a `al_desencolado` fuera del lock. `_pista_del_item` sin nombre: `cancion=None`, `titulo` = artista si hay,
  si no la URI (solo para mostrar). La radio, en `_al_cambiar_agenda`, busca su emisora por nombre y aplica
  `replace(suya, corrimiento=…, pedidos=…)`; si no la tiene, usa la recibida.
- [ ] **Step 4:** `.venv/bin/pytest -q -p no:cacheprovider` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Spotify: sacar el encolado de la cola descarta su anuncio; ítem sin nombre y rescan con pedido"`

### Task 4: Documentación, Beans y prueba real

**Files:**
- Modify: `README.md` (sección «Peticiones»), `docs/project-context.md`
- Beans: completar CASSETTE-FM-0av0 y CASSETTE-FM-rvd4.

- [ ] **Step 1:** README: dos pedidos seguidos → el DJ cierra el primero y presenta el segundo; sacar de la cola o
  saltear un pedido no deja anuncios colgados.
- [ ] **Step 2:** con el usuario (reiniciar está autorizado): encolar dos temas con tiempo (el segundo con anuncio
  «seguidas»), sacar un encolado sin poner otro (no queda «antes» en `intervenciones.json`), saltear un pedido a la
  mitad (no queda «después»).
- [ ] **Step 3: Commit** `git commit -m "Documentar el cierre de las peticiones y cerrar sus tareas de Beans"`
