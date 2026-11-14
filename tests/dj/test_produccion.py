import json
import random
import wave
from pathlib import Path

import pytest

from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ
from cassette_fm.dj.guiones import RegistroGuiones
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import IDIOMAS, Pedido, Tema
from cassette_fm.dj.produccion import Productor, Resultado
from cassette_fm.dj.sintetizador import ErrorModelos
from cassette_fm.dj.texto_voz import preparar
from datetime import datetime, timezone


def fonemizar(texto, lang):
    return f"<{lang}:{texto}>"


class SintetizadorFalso:
    def __init__(self, duraciones=(5.0,), error=None):
        self.duraciones = list(duraciones)
        self.llamadas = []
        self.velocidades = []
        self.textos = []
        self.error = error

    def sintetizar(self, fonemas, voz, lang, salida, velocidad=None, texto=None):
        self.llamadas.append((fonemas, voz, lang, Path(salida)))
        self.velocidades.append(velocidad)
        self.textos.append(texto)
        if self.error:
            raise self.error
        dur = self.duraciones.pop(0) if len(self.duraciones) > 1 else self.duraciones[0]
        salida = Path(salida)
        salida.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(salida), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
            w.writeframes(b"\0\0" * 80)
        return dur


@pytest.fixture
def montaje(tmp_path):
    rutas = RutasDJ(config=tmp_path / "cfg" / "config.toml", estado=tmp_path / "estado", clips=tmp_path / "clips")
    guiones = RegistroGuiones(rutas.guiones)

    def crear(sintetizador=None, lexico=None):
        s = sintetizador or SintetizadorFalso()
        return Productor(ConfigServicioDJ(), rutas, s, fonemizar, lexico or Lexico({"Daddy Yankee": "en-us"}),
                         guiones, azar=random.Random(1)), s

    return crear, rutas, guiones


def test_produce_el_clip_en_clips_y_anota_el_guion(montaje, hacer_pedido):
    crear, rutas, guiones = montaje
    productor, _ = crear()
    r = productor.producir(hacer_pedido("abc"))
    assert isinstance(r, Resultado) and r.audio == rutas.clips / "abc.wav" and r.audio.exists()
    assert r.duracion == 5.0 and r.voz == "em_santa" and r.idioma == "es" and "cancion" in r.ingredientes
    (g,) = guiones.ultimos(10)
    for campo in ("ts", "id", "estacion", "idioma", "voz", "momento", "anterior", "siguiente", "fuente",
                  "ingredientes", "texto", "marcado", "fonemas", "duracion", "audio"):
        assert campo in g, campo
    assert g["fuente"] == "plantilla" and g["id"] == "abc" and g["siguiente"]["artista"] == "Foreigner"
    assert "{" not in g["texto"] and "{" in g["marcado"]
    assert g["texto"] == r.texto and g["marcado"] == r.marcado


def test_el_guion_alcanza_para_volver_a_sintetizar(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear()
    productor.producir(hacer_pedido("abc", idioma="en"))
    (g,) = guiones.ultimos(1)
    again = preparar(g["marcado"], IDIOMAS[g["idioma"]], fonemizar)
    assert again.fonemas == g["fonemas"] and again.texto == g["texto"]


def test_reintenta_si_el_clip_es_demasiado_largo(montaje, hacer_pedido):
    crear, rutas, guiones = montaje
    productor, sint = crear(SintetizadorFalso(duraciones=[20.0, 20.0, 5.0]))
    r = productor.producir(hacer_pedido("abc", duracion_maxima_segundos=10))
    assert r.duracion == 5.0 and len(sint.llamadas) == 3
    assert [p.name for p in rutas.clips.iterdir()] == ["abc.wav"]      # los descartados no quedan en disco
    registros = guiones.ultimos(10)
    assert [bool(x.get("descartado")) for x in registros] == [True, True, False]


def test_los_reintentos_acortan_el_texto(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear(SintetizadorFalso(duraciones=[30.0, 5.0]))
    productor.producir(hacer_pedido("abc", duracion_maxima_segundos=10))
    primero, segundo = guiones.ultimos(2)
    assert len(segundo["texto"].split()) <= len(primero["texto"].split())


def test_falla_si_ningun_intento_entra(montaje, hacer_pedido):
    crear, rutas, guiones = montaje
    productor, _ = crear(SintetizadorFalso(duraciones=[20.0]))
    with pytest.raises(ValueError) as exc:
        productor.producir(hacer_pedido("abc", duracion_maxima_segundos=10))
    assert "20.0" in str(exc.value) and "10" in str(exc.value)
    assert not list(rutas.clips.glob("*"))
    assert "error" in guiones.ultimos(10)[-1]


def test_propaga_ErrorModelos_y_lo_anota(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear(SintetizadorFalso(error=ErrorModelos("faltan los modelos: corré `cassette-dj modelos`")))
    with pytest.raises(ErrorModelos):
        productor.producir(hacer_pedido("abc"))
    assert "cassette-dj modelos" in guiones.ultimos(1)[0]["error"]


def test_el_id_no_puede_escapar_de_clips(montaje, tmp_path):
    crear, rutas, _ = montaje
    productor, sint = crear()
    malo = Pedido(id="../fuera", estacion="L", idioma="es", voz="v", momento=datetime(2026, 1, 1, tzinfo=timezone.utc),
                  anterior=None, siguiente=Tema("A", "B"))
    with pytest.raises(ValueError):
        productor.producir(malo)
    assert sint.llamadas == [] and not (tmp_path / "fuera.wav").exists()


def test_usa_el_idioma_y_la_voz_del_pedido(montaje, hacer_pedido):
    crear, _, _ = montaje
    productor, sint = crear()
    productor.producir(hacer_pedido("a", idioma="en-gb", voz="bm_george"))
    fonemas, voz, lang, _ = sint.llamadas[0]
    assert voz == "bm_george" and lang == "en-gb" and "<en-gb:" in fonemas


def test_los_nombres_en_otro_idioma_llevan_su_marca(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear()
    for i in range(30):
        productor.producir(hacer_pedido(f"p{i}", siguiente={"artista": "Daddy Yankee", "titulo": "Gasolina"}))
    marcados = [g["marcado"] for g in guiones.ultimos(100)]
    assert any("{en-us:Daddy Yankee}" in m for m in marcados)
    assert all("{es:Daddy Yankee}" not in m for m in marcados)


def test_el_productor_habla_en_la_zona_horaria_configurada(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear()
    for i in range(40):
        productor.producir(hacer_pedido(f"z{i}", momento="2026-11-14T00:47:00+00:00"))   # 21:47 en Buenos Aires
    textos = [g["texto"] for g in guiones.ultimos(100) if "hora" in g.get("ingredientes", [])]
    assert textos and all("diez menos cuarto" in t for t in textos)


def test_la_velocidad_del_pedido_llega_al_sintetizador(montaje, hacer_pedido):
    crear, _, _ = montaje
    productor, sint = crear()
    productor.producir(hacer_pedido("v1", velocidad=1.2))
    productor.producir(hacer_pedido("v2"))
    assert [v for v in sint.velocidades] == [1.2, None]


def test_el_texto_limpio_llega_al_sintetizador_para_los_motores_que_no_usan_fonemas(montaje, hacer_pedido):
    crear, _, _ = montaje
    productor, sint = crear()
    r = productor.producir(hacer_pedido("t1"))
    from cassette_fm.dj.texto_voz import texto_para_piper
    assert sint.textos == [texto_para_piper(r.marcado)]
