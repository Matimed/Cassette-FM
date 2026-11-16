# Escuchar la voz antes de crear la emisora

Diseño corto, 2026-11-16. Sigue al [modal de emisora nueva](2026-11-16-modal-emisora-nueva-design.md).

## Para qué

Elegir la voz del DJ de oído: en el modal, un botón ▶ al lado de la voz elegida que la hace decir
"Hola, soy dora y estás escuchando Synthwave F.M." (con el nombre que se escribió en el modal).

## Enfoques

- **Un pedido nuevo al servicio DJ** (elegido por el usuario): el servicio ya tiene Kokoro y Piper cargados y genera
  la frase en uno o dos segundos. Si el DJ está caído no hay muestra (el modal lo dice).
- **Colgarse de `cassette-dj voz-prueba`:** vuelve a sintetizar el último guion real del idioma; carga el modelo en
  cada llamada (~2,5 s y ~600 MB), falla con Piper y sin guiones previos no tiene qué decir. Descartado, pero comparte
  la lógica nueva (ver abajo) y de paso deja de fallar con Piper.

## Diseño

```
│ Voz       [dora                     ▾] [▶] │     ▶ → … (generando) → ■ (sonando; apretarlo corta) → ▶
```

1. **La frase** (en el servicio DJ, un solo lugar): español `Hola, soy {voz} y estás escuchando {radio}.`; inglés
   (`en` y `en-gb`) `Hi, I'm {voz}, and you're listening to {radio}.` `{voz}` es el alias con `_` como espacio
   (`alex_santa` → "alex santa"); los dos nombres se marcan con `marcar` como nombres, igual que las plantillas.
   Sin nombre de radio (campo vacío): `Hola, soy {voz}, la voz de tu nueva radio.` / `Hi, I'm {voz}, the voice of
   your new station.` (decisión propia: `preparar` pide al menos 4 palabras).
2. **Lógica compartida:** una función que prepara un texto marcado y lo sintetiza (fonemas para Kokoro, texto para
   Piper) la usan el pedido nuevo, `voz-prueba` (que hoy no le pasa el texto a Piper y por eso falla) y las dos
   síntesis de `produccion.py`.
3. **Servicio DJ:** `POST /muestra {"voz", "idioma", "radio"}` → `200` con el WAV (`audio/wav`), sintetizado en el
   momento (el candado del sintetizador lo ordena con las intervenciones en curso). Voz o idioma inválidos → `400`;
   faltan modelos → `503`.
4. **CLI:** `cassette-dj muestra --voz dora --idioma es [--radio "Synthwave F.M."]` pide la muestra al servicio, la
   guarda en `~/.cache/cassette-dj/muestras/` (por voz, idioma y radio: la segunda vez no se vuelve a pedir) e
   imprime la ruta del WAV. Servicio caído → error de una línea.
5. **Applet:** botón ▶ a la derecha del desplegable de voz. Con "Al azar", desactivado. Al apretarlo corre
   `cassette-dj muestra` con la voz, su idioma y el nombre escrito (sin shell, como `cassette nueva`) mostrando `…`;
   después reproduce el WAV con `mpv` mostrando `■` (apretarlo corta el mpv). Elegir otra voz, cerrar el modal o Crear cortan la muestra.
   Un error (DJ caído, `cassette-dj` no encontrado) va en rojo en el modal, como los demás. Suena encima de la música,
   sin bajarla (pedido del usuario: directo desde el applet). Límite: 60 s.

**Fuera:** bajar la música durante la muestra, elegir la velocidad, muestras en otros lugares que no sean el modal.

## Para quien lo construye

- La frase, los argumentos de `cassette-dj muestra` y los estados del botón (▶ / … / ■ / desactivado) son lógica
  pura y se prueban sin Cinnamon (Python y `logic.js`); `applet.js` solo arma el botón y lanza el proceso.
- Prueba real: pedir una muestra por CLI con una voz de Kokoro y una de Piper; en el modal, recargar el applet
  (y reiniciar Cinnamon si cambió `logic.js`).
