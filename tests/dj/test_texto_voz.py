import pytest

from cassette_fm.dj.texto_voz import Preparado, aplicar_seseo, limpiar, marcar, preparar, tramos


def falso(texto, lang):
    return f"<{lang}:{texto}>"


# --- marcar ---

def test_marcar_limpia_el_nombre():
    assert marcar('Héctor "El Father"', "es") == "{es:Héctor El Father}"
    assert marcar("Tito “El Bambino”", "es") == "{es:Tito El Bambino}"
    m = marcar("Raro {nombre}\ncon saltos", "en-us")
    assert m == "{en-us:Raro nombre con saltos}" and "\n" not in m


def test_marcar_nombre_vacio_falla():
    for vacio in ("", "   ", '""', "{}"):
        with pytest.raises(ValueError):
            marcar(vacio, "es")


# --- tramos ---

def test_tramos_separa_por_idioma():
    assert tramos("Seguimos con {en-us:Daddy Yankee} en vivo", "es") == [
        ("Seguimos con", "es"), ("Daddy Yankee", "en-us"), ("en vivo", "es")]


def test_tramos_sin_marcas_es_un_solo_tramo():
    assert tramos("Hola gente", "en-us") == [("Hola gente", "en-us")]


def test_tramos_llaves_sin_cerrar_son_texto():
    assert tramos("hola {mundo sin cerrar", "es") == [("hola {mundo sin cerrar", "es")]


def test_tramos_vacios_se_omiten():
    assert tramos("{es:}  {en-us:   }", "es") == []
    assert tramos("", "es") == []


def test_tramos_nombre_con_enie_y_acentos():
    assert tramos("con {es:Música Ñandú} hoy", "en-us") == [
        ("con", "en-us"), ("Música Ñandú", "es"), ("hoy", "en-us")]


def test_tramos_nombre_con_dos_puntos_adentro():
    assert tramos("{es:Re: Mix}", "en-us") == [("Re: Mix", "es")]


# --- limpiar ---

def test_quita_signos_de_pausa():
    r = limpiar("¡Qué tal gente! Son las nueve en Buenos Aires con calor.", "es")
    assert "¡" not in r and "!" not in r and "¿" not in r
    assert r == "Qué tal gente son las nueve en Buenos Aires con calor."


def test_ampersand_segun_idioma():
    assert limpiar("Escuchamos a {es:Zion & Lennox} con mucho entusiasmo hoy.", "es") == \
        "Escuchamos a {es:Zion y Lennox} con mucho entusiasmo hoy."
    assert limpiar("We are playing {en-us:Zion & Lennox} with a lot of energy.", "en-us") == \
        "We are playing {en-us:Zion and Lennox} with a lot of energy."


def test_comas_cortas_se_quitan_y_largas_se_conservan():
    assert limpiar("Son las nueve, dieciocho grados y todo bien", "es") == \
        "Son las nueve dieciocho grados y todo bien."
    largo = "Estamos escuchando la mejor música de la zona, con todos los temas que más te gustan"
    assert limpiar(largo, "es") == largo + "."


def test_dos_puntos_y_punto_y_coma_se_tratan_como_comas():
    assert limpiar("A todo volumen: con los mejores temas del año para vos", "es") == \
        "A todo volumen con los mejores temas del año para vos."
    largo = "Seguimos escuchando la mejor música del momento; con todos los temas que más te gustan"
    assert "," in limpiar(largo, "es") and ";" not in limpiar(largo, "es")


def test_oracion_corta_se_une_a_la_anterior():
    r = limpiar("Son las nueve en Buenos Aires con mucho calor. Hay veinte grados.", "es")
    assert r == "Son las nueve en Buenos Aires con mucho calor hay veinte grados."


def test_oracion_corta_inicial_se_une_a_la_siguiente():
    r = limpiar("Hola gente. Son las nueve en Buenos Aires con mucho calor hoy.", "es")
    assert r == "Hola gente son las nueve en Buenos Aires con mucho calor hoy."


def test_una_sola_oracion_corta_se_deja():
    assert limpiar("Hola gente.", "es") == "Hola gente."


def test_los_nombres_marcados_cuentan_como_palabras():
    r = limpiar("Ahora {en-us:Wisin & Yandel con Daddy Yankee}. Seguimos con mucha música para todos.", "es")
    # la primera oración tiene 7 palabras (el nombre cuenta las suyas): no se une a la siguiente
    assert r == "Ahora {en-us:Wisin and Yandel con Daddy Yankee}. Seguimos con mucha música para todos."


def test_conserva_apostrofes_dentro_de_palabras():
    assert "don't" in limpiar("We don't stop the music here tonight on the radio.", "en-us")


def test_termina_con_punto_y_respeta_la_pregunta():
    assert limpiar("Seguimos con la música de siempre", "es").endswith(".")
    assert limpiar("Querés seguir escuchando con nosotros hoy?", "es").endswith("?")


def test_los_nombres_pierden_la_puntuacion_que_hace_pausas():
    """Review: Kokoro trata `. ! ? , ; :` como marcas de pausa también adentro de un nombre."""
    r = limpiar('Escuchamos {es:Héctor "El Father", Jowell} con mucho entusiasmo hoy.', "es")
    assert "{es:Héctor El Father Jowell}" in r
    for crudo, esperado in [("Mr. Big", "Mr Big"), ("Panic! At The Disco", "Panic At The Disco"),
                            ("P!nk", "P nk"), ("¿Quién será?", "Quién será"), ("Re: Mix; uno", "Re Mix uno")]:
        assert "{en-us:" + esperado + "}" in limpiar("Ahora suena {en-us:" + crudo + "} para todos ustedes hoy.", "es")


def test_ampersand_usa_el_idioma_del_nombre():
    """Review: `&` dentro de un nombre se lee con el idioma del nombre, no con el de la frase."""
    es = limpiar("Ahora suena {en-us:Earth, Wind & Fire} para todos ustedes en vivo.", "es")
    assert "{en-us:Earth Wind and Fire}" in es
    en = limpiar("Now playing {es:Wisin & Yandel} for everybody listening out there.", "en-us")
    assert "{es:Wisin y Yandel}" in en


def test_el_texto_no_puede_inyectar_los_marcadores_internos():
    r = limpiar("Hola \ue0000\ue001 gente de todo el mundo que nos escucha hoy.", "es")
    assert "\ue000" not in r and "\ue001" not in r


def test_nombre_que_queda_vacio_se_descarta_sin_romper():
    assert "{" not in limpiar("Ahora suena {es:..!!} para todos los que nos escuchan hoy.", "es")


def test_espacios_normalizados():
    assert limpiar("  Son   las nueve  en   Buenos   Aires  con calor  ", "es") == \
        "Son las nueve en Buenos Aires con calor."


def test_es_idempotente():
    textos = [
        "¡Qué tal gente! Son las nueve, dieciocho grados y todo bien. Seguimos con la música.",
        "Hola. Buenas noches a todos los que nos escuchan desde cualquier lugar del mundo.",
        "Estamos escuchando la mejor música de la zona, con todos los temas que más te gustan",
        "Ahora suena {en-us:Daddy Yankee} con Gasolina. Seguimos con mucha música para todos.",
        "Son las diez menos diez en Buenos Aires con veinte grados y cielo despejado hoy.",
        "Hola gente.",
    ]
    for t in textos:
        una = limpiar(t, "es")
        assert limpiar(una, "es") == una


# --- seseo ---

def test_aplicar_seseo():
    assert aplicar_seseo("djeθjˈotʃo ɡɾˈaθjas") == "djesjˈotʃo ɡɾˈasjas"
    assert aplicar_seseo("sˈon las") == "sˈon las"


# --- preparar ---

def test_el_seseo_solo_va_en_los_tramos_en_espanol():
    def f(texto, lang):
        return "θ"
    p = preparar("hola gente {en-us:Daddy Yankee} que tal todos los amigos", "es", f)
    assert p.fonemas == "s θ s"


def test_texto_marcado_y_fonemas():
    p = preparar("Seguimos con {en-us:Daddy Yankee} en vivo por acá para todos vos.", "es", falso)
    assert isinstance(p, Preparado)
    assert p.texto == "Seguimos con Daddy Yankee en vivo por acá para todos vos."
    assert p.marcado == "Seguimos con {en-us:Daddy Yankee} en vivo por acá para todos vos."
    assert p.fonemas.startswith("<es:Seguimos con> <en-us:Daddy Yankee> <es:en vivo")


def test_el_idioma_base_en_usa_en_us():
    p = preparar("Nine twenty here in {es:Buenos Aires} tonight with the best music.", "en-us", falso)
    assert "<en-us:Nine twenty here in>" in p.fonemas and "<es:Buenos Aires>" in p.fonemas


def test_preparar_aplica_limpiar():
    p = preparar("¡Qué tal gente! Seguimos con la mejor música del momento para vos.", "es", falso)
    assert "¡" not in p.marcado and "!" not in p.marcado


def test_nombres_dificiles_no_rompen_la_preparacion():
    marcado = ('Escuchamos a ' + marcar('Héctor "El Father"', "es") + ' y a ' + marcar("Zion & Lennox", "es")
               + ' con ' + marcar("Música Ñandú", "es") + ' para todos.')
    p = preparar(marcado, "es", falso)
    assert "Héctor El Father" in p.texto and "Zion y Lennox" in p.texto and "Música Ñandú" in p.texto
    assert "{" not in p.texto and "}" not in p.texto


def test_integracion_con_el_fonemizador_real():
    kokoro_onnx = pytest.importorskip("kokoro_onnx")
    fon = kokoro_onnx.Tokenizer().phonemize
    es = preparar("Qué tal gente son las nueve en Buenos Aires con dieciocho grados y gracias a todos", "es", fon)
    assert "θ" not in es.fonemas and "s" in es.fonemas
    con_ingles = preparar("Seguimos con {en-us:Daddy Yankee} en vivo para todos ustedes hoy", "es", fon)
    assert "æ" in con_ingles.fonemas
    en = preparar("Nine twenty here in {es:Buenos Aires} tonight with the best music", "en-us", fon)
    assert "bwˈenos" in en.fonemas


def test_los_tramos_contiguos_del_mismo_idioma_se_fonemizan_juntos():
    llamadas = []

    def registrador(texto, lang):
        llamadas.append((texto, lang))
        return f"<{lang}:{texto}>"

    preparar("Ahora suena {es:Gasolina} de {es:Dadi Yanki} para todos nosotros.", "es", registrador)
    assert llamadas == [("Ahora suena Gasolina de Dadi Yanki para todos nosotros.", "es")]
    llamadas.clear()
    preparar("Ahora suena {es:Gasolina} de {en-us:Daddy Yankee} para todos nosotros.", "es", registrador)
    assert [l for _, l in llamadas] == ["es", "en-us", "es"]


from cassette_fm.dj.texto_voz import texto_para_piper


@pytest.mark.parametrize("marcado, esperado", [
    ("Estamos en {es:Reguetón 2000} esta noche y ahora suena {es:Sexy Movimiento} de {es:Dadi Yanki} para todos nosotros.",
     "Estamos en Reguetón 2000 esta noche, y ahora suena Sexy Movimiento, de Dadi Yanki, para todos nosotros."),
    ("En {es:Reguetón 2000} son las dos en punto y toca el turno de {es:Nicky Jam} con {es:Sexy Movimiento} sin cortes.",
     "En Reguetón 2000 son las dos en punto, y toca el turno de Nicky Jam, con Sexy Movimiento, sin cortes."),
    ("Ahora suena {es:Gasolina} de {en-us:Daddy Yankee}.", "Ahora suena Gasolina de Daddy Yankee."),
    ("Sigue {es:Gasolina}. Y después {es:Lo Que Pasó}, para todos.", "Sigue Gasolina. Y después Lo Que Pasó, para todos."),
    ("Hola gente y bienvenidos.", "Hola gente y bienvenidos."),
])
def test_texto_para_piper_pone_comas_donde_se_respira(marcado, esperado):
    assert texto_para_piper(marcado) == esperado
