"""La frase de muestra de una voz: lo que se oye al apretar ▶ en el modal de emisora nueva del applet."""
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import IDIOMAS
from cassette_fm.dj.texto_voz import marcar


def frase_muestra(voz: str, idioma: str, radio: str, lexico: Lexico) -> str:
    """"Hola, soy dora y estás escuchando Synthwave F.M.", marcada para la voz (`idioma`: una clave de `IDIOMAS`;
    sin radio, una presentación de la voz sola)."""
    lang = IDIOMAS[idioma]
    quien = marcar(voz.replace("_", " "), lang)
    es = idioma == "es"
    radio = radio.strip()
    if not radio:
        return f"Hola, soy {quien}, la voz de tu nueva radio." if es else \
            f"Hi, I'm {quien}, the voice of your new station."
    donde = marcar(lexico.pronunciacion(radio), lexico.idioma_de(radio, lang))
    return f"Hola, soy {quien} y estás escuchando {donde}." if es else f"Hi, I'm {quien}, and you're listening to {donde}."
