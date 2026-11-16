from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.muestra import frase_muestra


def test_frase_en_espanol_y_en_ingles():
    assert frase_muestra("dora", "es", "Synthwave F.M.", Lexico()) == \
        "Hola, soy {es:dora} y estás escuchando {es:Synthwave F.M.}."
    assert frase_muestra("alex_santa", "en-gb", "Sing", Lexico()) == \
        "Hi, I'm {en-gb:alex santa}, and you're listening to {en-gb:Sing}."


def test_frase_sin_radio():
    assert frase_muestra("dora", "es", "  ", Lexico()) == "Hola, soy {es:dora}, la voz de tu nueva radio."
    assert frase_muestra("puck", "en", "", Lexico()) == "Hi, I'm {en-us:puck}, the voice of your new station."


def test_una_radio_con_llaves_no_rompe_el_marcado():
    assert frase_muestra("dora", "es", "Rock {&} Roll", Lexico()) == \
        "Hola, soy {es:dora} y estás escuchando {es:Rock & Roll}."
