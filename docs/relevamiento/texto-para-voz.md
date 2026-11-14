# Relevamiento: cómo preparar el texto para la voz (Kokoro)

> Pruebas del 13/11/2026 con `kokoro-onnx` (modelo v1.0) y la voz `em_santa` (español) y `am_michael`/`af_heart`
> (inglés), escuchadas por el usuario. Es la base de la capa "texto para voz" del DJ (Etapa 3).
> Scripts de las pruebas en `anexos/kokoro-fonemas-hibrido.py`, `kokoro-puntuacion.py` y `kokoro-seseo.py`
> (reciben como argumento un directorio con `modelos/` y `clips/`).

## Qué problemas había

Las voces leían mal nombres en otro idioma ("Daddy Yankee", "Buenos Aires" en inglés), hacían pausas raras con
`¡ ! ,` y acentuaban de forma antinatural el final de algunas frases.

## Qué se probó y qué se concluyó

| Idea | Resultado |
|---|---|
| Pasar todo a minúsculas | **No cambia nada.** Los fonemas son idénticos con y sin mayúsculas. |
| Sacar `¡ ! ¿` y comas, usar puntos | Mejora las pausas. |
| Reescribir el nombre como suena ("dadi yanqui") | En español funciona. **En inglés empeora**: una palabra que no existe en inglés se deletrea letra por letra (`bwenos` → `bˈiːwˈiːnoʊz`). |
| **Fonemas por tramo y por idioma** ("híbrido") | **Gana.** Se fonemiza cada tramo en su idioma y se le pasa el resultado al modelo con `is_phonemes=True`: "Buenos Aires" con fonemas españoles dentro de una frase en inglés, "Daddy Yankee" con fonemas ingleses dentro de una frase en español. Entre "dadi yanqui" y el híbrido en español el usuario no percibe diferencia: se usa un solo mecanismo (fonemas). |
| Oraciones cortas sueltas ("…Buenos Aires. Hay dieciocho grados.") | **Mal.** El punto tras una oración corta hace que el modelo baje el tono y acentúe la última palabra, como un titular. Con una oración más larga el efecto desaparece. |
| `θ` → `s` en los fonemas del español | **Gana por mucho.** El modelo lee "dieciocho", "gracias", "ciudad" con la θ del español de España; cambiarla por `s` da la pronunciación argentina. |

## Reglas que salen de acá (para la capa texto-para-voz)

1. Fonemizar por tramos con el idioma de cada nombre propio; el resto, en el idioma de la voz.
2. Español: reemplazar `θ` por `s` en los fonemas (seseo rioplatense).
3. Sin `¡ ! ¿`; evitar comas innecesarias.
4. **No dejar oraciones cortas sueltas**: unirlas a la anterior con un conector ("con dieciocho grados") o pedirle al LLM
   frases largas.
5. Las mayúsculas no importan.

## Datos de rendimiento (Ryzen 5 5600G, solo CPU)

Sintetizar ~9 s de audio tarda ~3 s (factor ~0,3). El modelo pesa 326 MB (+28 MB de voces). Hacer el TTS en la PC
local es viable; el LLM es lo caro.

## Qué ofrece `kokoro-onnx` por dentro (v0.6.1, revisado el 13/11/2026)

- `Tokenizer().phonemize(texto, lang)` funciona **sin cargar el modelo** (solo espeak): sirve para preparar el texto de forma
  liviana y para probarlo sin los 326 MB.
- `Kokoro.create(...)` acepta `sentence_pause` (0,25 s por defecto), `clause_pause` (0,1 s) y `continuous`. Las pausas se
  **completan hasta ese valor** después de un punto o `!` y de una coma o `;`; el modelo deja además su propio silencio.
  Son los controles directos de las "pausas raras" y quedan como ajustes del servicio DJ para afinar con frases reales.
  `continuous=True` sintetiza el texto en ventanas superpuestas (a probar con frases largas).
- `voice` puede ser un vector de estilo (`numpy`) en vez de un nombre: **mezclar voces** es promediar sus vectores.
- Hay 54 voces; en español solo `ef_dora`, `em_alex`, `em_santa`. Cargado, el proceso ronda los 455 MB.

## Prueba en uso real (parte 1 del DJ)

El 13/11/2026 el usuario escuchó la voz `em_santa` (con "s" argentina) saliendo por el DJ de la radio real, con la
música bajada: funciona y es entendible, **pero no le encanta la voz**. Kokoro v1.0 solo trae 3 voces en español
(`ef_dora`, `em_alex`, `em_santa`) y las otras dos ya se habían descartado. Alternativas a evaluar: mezclar voces de
Kokoro (promediar sus vectores de estilo), `es-MX-JorgeNeural` / `es-US-AlonsoNeural` de edge-tts (les gustaron en las
pruebas; necesitan internet) u otro modelo. La voz es un dato por estación, así que cambiarla no toca el resto.

## Pendiente de probar

- Más nombres reales de la biblioteca (artistas, canciones) para ver si el diccionario de idioma por nombre alcanza.
- Variante rioplatense de la `y`/`ll` (rehilamiento: "yo" → "sho"): no se probó.
