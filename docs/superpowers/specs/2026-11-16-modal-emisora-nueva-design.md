# Crear una emisora desde el applet

Diseño corto, 2026-11-16. Segundo paso de [`cassette nueva`](2026-11-16-emisora-nueva-design.md).

## Para qué

Crear una emisora de Spotify sin abrir la terminal: desde el menú del applet, un modal con nombre, link de la playlist,
idioma y voz del DJ. Sirve también para tener dos emisoras con la misma playlist como alternativa a saltear un tema
(eso ya funciona hoy: solo el nombre no se puede repetir, y el orden de cada emisora sale de su nombre).

## Enfoques

- **El applet corre `cassette`** (elegido por el usuario): `cassette voces --json` para llenar la lista de voces y
  `cassette nueva …` para crear. Reusa todo lo probado, los errores son los mismos que en la terminal y no lo limita el
  timeout de 3 s del HTTP del applet. Costo: el applet lanza procesos además de hablar HTTP.
- **Dos pedidos nuevos al servicio de la radio:** muda la lógica de `cassette nueva` al servicio (leer el config del
  DJ, bajar la playlist mientras atiende al applet, estirar el timeout). Más código y más riesgo, mismo resultado.
- **Voces desde `GET /voces` del servicio DJ:** dos canales, no sabe qué voces están en uso ni su idioma, y sin el DJ
  el modal queda sin voces.

## Diseño

```
┌ Emisora nueva ────────────────────────────┐
│ Nombre    [Sing 2                       ] │
│ Playlist  [https://open.spotify.com/…    ] │
│ Idioma    (Cualquiera) (Español) (Inglés)  │
│ Voz       [Al azar                    ▾] │
│ ⚠ la playlist «X» no es tuya…             │
│                       [Cancelar]  [Crear] │
└───────────────────────────────────────────┘

  con la voz desplegada:
│ Voz       [dora                       ▴] │
│           │ Al azar                     │ │
│           │ daniela                     │ │
│           │ dora                        │ │
│           │ claude · Sing               │ │
│           │ …                  (scroll) │ │
```

1. **`cassette voces [--json]`** (nuevo, en la CLI): los alias de `[voces]` que sirven para una emisora (hablan
   español o inglés, con `emisora_nueva.idioma_de_voz`), con su voz, su idioma y las emisoras que ya los usan. Sin
   `--json`, una tabla para la terminal; con `--json`, una lista
   `[{"alias", "voz", "idioma", "emisoras": [...]}]` para el applet. No necesita la radio corriendo.
2. **Entrada "Nueva emisora…"** en el menú del applet, debajo de las emisoras (antes de "Apagar"). Como el listado,
   aparece cuando la radio responde.
3. **Modal** (`ModalDialog` de Cinnamon). Al abrirse corre `cassette voces --json`.
   - Idioma: tres botones excluyentes, Cualquiera / Español / Inglés (`en-gb` cuenta como inglés).
   - Voz: un desplegable (pedido del usuario) con "Al azar" primero y después los alias del idioma elegido (todos con
     Cualquiera). Los que ya usa una emisora llevan su nombre al lado (`claude · Sing`): se pueden elegir igual. El
     combo de Cinnamon (`PopupComboBoxMenuItem`) solo funciona dentro de un menú, no en un `ModalDialog`: el
     desplegable se arma dentro del diálogo, un botón con la voz elegida y `▾` que abre debajo una lista con scroll y
     se pliega al elegir.
   - Elegir una voz con idioma Cualquiera pone el idioma de esa voz. Cambiar a un idioma que no habla la voz elegida
     vuelve la voz a "Al azar".
   - Crear corre `cassette nueva NOMBRE LINK [--voz ALIAS] [--idioma es|en]` (con "Al azar" va sin `--voz`; con
     Cualquiera, sin `--idioma`).
4. **Mientras crea:** Crear dice "Creando…"; Crear, Cancelar y Escape quedan desactivados (así un doble clic no corre
   dos `cassette nueva` a la vez). Si en 60 s no terminó, se corta el proceso y lo dice.
5. **Resultado:** sale bien → se cierra el modal y el applet refresca el estado (la radio ya está en la emisora nueva).
   Falla → el texto de error de `cassette nueva` (su stderr) en rojo dentro del modal, sin borrar lo escrito. Si no se
   encuentra `cassette` (en el PATH o en `~/.local/bin`), o falla `cassette voces`, también se dice ahí.

**Fuera:** emisoras de carpetas locales, editar o borrar emisoras, velocidad y personalidad del DJ.

## Para quien lo construye

- La lógica pura (qué voces mostrar según el idioma, qué idioma fija una voz, los argumentos del comando, el texto de
  error a mostrar) va en `logic.js` y se prueba con Node, como el resto del applet; `applet.js` solo arma widgets y
  lanza procesos (`Gio.Subprocess`, asíncrono: el panel nunca se congela).
- La prueba real es en Cinnamon: recargar el applet y crear una emisora de verdad.
