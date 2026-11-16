from pathlib import Path

from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.reproductores import Reproductores

ESTATICA = Path("/tmp/estatica.wav")


class Falso:
    def __init__(self, nombre, registro):
        self.nombre, self.registro = nombre, registro
        self.pista_actual = None
        self.al_cambiar_pista = self.al_fallar = self.al_sonar = None

    def _r(self, *a):
        self.registro.append((self.nombre, *a))

    def sintonizar(self, e): self._r("sintonizar", e.nombre)
    def detener(self): self._r("detener")
    def estatica(self, ruta): self._r("estatica", ruta)
    def volumen(self, v): self._r("volumen", v); return v
    def atenuar(self, f, s=0.0): self._r("atenuar", f, s)
    def posicion(self): return 1.0 if self.nombre == "mpv" else 2.0
    def asegurar(self): self._r("asegurar")
    def actualizar(self, e): self._r("actualizar", e.nombre)


def est(nombre, fuente):
    return Estacion(nombre, (Pista(None if fuente == "spotify" else Path("/m/a.mp3"), 100.0, "t", fuente="spotify"
                                   if fuente == "spotify" else "local", uri="spotify:track:x"),), fuente=fuente)


def armar():
    registro = []
    mpv, spot = Falso("mpv", registro), Falso("spotify", registro)
    return Reproductores(mpv, spot, ESTATICA), mpv, spot, registro


def test_sintonizar_spotify_pone_la_estatica_y_la_saca_al_sonar():
    r, mpv, spot, reg = armar()
    r.sintonizar(est("Sing", "spotify"))
    assert reg == [("mpv", "detener"), ("mpv", "atenuar", 1.0, 0.0), ("mpv", "estatica", ESTATICA),
                   ("spotify", "sintonizar", "Sing")]
    spot.al_sonar()
    assert reg[-1] == ("mpv", "estatica", None)


def test_de_spotify_a_local_detiene_spotify_y_nunca_suenan_dos():
    r, mpv, spot, reg = armar()
    r.sintonizar(est("Sing", "spotify"))
    reg.clear()
    r.sintonizar(est("Local", "carpeta"))
    assert reg == [("spotify", "detener"), ("spotify", "atenuar", 1.0, 0.0), ("mpv", "sintonizar", "Local")]
    reg.clear()
    r.sintonizar(est("Otra", "carpeta"))
    assert reg == [("mpv", "sintonizar", "Otra")]          # local a local: Spotify no se toca


def test_un_al_sonar_que_llega_tarde_no_saca_la_estatica_de_otra_sintonia():
    r, mpv, spot, reg = armar()
    r.sintonizar(est("Sing", "spotify"))
    r.sintonizar(est("Local", "carpeta"))
    reg.clear()
    spot.al_sonar()                                         # ya no está activo Spotify
    assert reg == []


def test_volumen_va_a_los_dos_y_atenuar_y_posicion_al_activo():
    r, mpv, spot, reg = armar()
    assert r.volumen(55) == 55
    assert ("mpv", "volumen", 55) in reg and ("spotify", "volumen", 55) in reg
    r.sintonizar(est("Sing", "spotify"))
    reg.clear()
    r.atenuar(0.6, 0.4)
    assert reg == [("spotify", "atenuar", 0.6, 0.4)] and r.posicion() == 2.0


def test_los_avisos_de_los_dos_llegan_a_la_radio():
    r, mpv, spot, _ = armar()
    vistos = []
    r.al_cambiar_pista = lambda p, e: vistos.append(("cambio", e))
    r.al_fallar = lambda e, motivo=None: vistos.append(("falla", e, motivo))
    mpv.al_cambiar_pista("p", "A")
    spot.al_cambiar_pista("p", "B")
    mpv.al_fallar("A")
    spot.al_fallar("B", "sin red")
    assert vistos == [("cambio", "A"), ("cambio", "B"), ("falla", "A", None), ("falla", "B", "sin red")]


def test_pista_actual_es_la_del_activo():
    r, mpv, spot, _ = armar()
    mpv.pista_actual, spot.pista_actual = "pm", "ps"
    assert r.pista_actual == "pm"
    r.sintonizar(est("Sing", "spotify"))
    assert r.pista_actual == "ps"


def test_detener_para_todo():
    r, mpv, spot, reg = armar()
    r.sintonizar(est("Sing", "spotify"))
    reg.clear()
    r.detener()
    assert ("spotify", "detener") in reg and ("mpv", "detener") in reg


def test_sin_spotify_configurado_una_emisora_de_spotify_es_un_error_claro():
    import pytest
    r = Reproductores(Falso("mpv", []), None, ESTATICA)
    with pytest.raises(ValueError, match="Spotify"):
        r.sintonizar(est("Sing", "spotify"))


def test_de_spotify_a_spotify_se_detiene_el_anterior():
    r, mpv, spot, reg = armar()
    r.sintonizar(est("A", "spotify"))
    reg.clear()
    r.sintonizar(est("B", "spotify"))
    assert reg.index(("spotify", "detener")) < reg.index(("spotify", "sintonizar", "B"))


def test_el_reproductor_que_se_deja_vuelve_al_volumen_pleno():
    r, mpv, spot, reg = armar()
    r.sintonizar(est("Sing", "spotify"))
    r.atenuar(0.6)
    reg.clear()
    r.sintonizar(est("Local", "carpeta"))
    assert ("spotify", "atenuar", 1.0, 0.0) in reg
    r.atenuar(0.6)
    reg.clear()
    r.sintonizar(est("Sing", "spotify"))
    assert ("mpv", "atenuar", 1.0, 0.0) in reg
    r.atenuar(0.6)
    reg.clear()
    r.detener()
    assert ("spotify", "atenuar", 1.0, 0.0) in reg


def test_reenvia_al_cambiar_agenda_y_al_encolado():
    r, _, spotify, _ = armar()
    vistos = []
    r.al_cambiar_agenda = lambda e, nuevo: vistos.append(("agenda", e, nuevo))
    r.al_encolado = lambda p, e, fin: vistos.append(("encolado", p, e, fin))
    spotify.al_cambiar_agenda("E", "P")
    spotify.al_encolado("P", "E", 9.0)
    assert vistos == [("agenda", "E", "P"), ("encolado", "P", "E", 9.0)]


def test_al_desencolado_llega_desde_spotify():
    r, _, spotify, _ = armar()
    vistos = []
    r.al_desencolado = vistos.append
    spotify.al_desencolado("P")
    assert vistos == ["P"]


def test_actualizar_llega_a_spotify_solo_si_esta_sonando():
    r, mpv, spot, reg = armar()
    r.actualizar(est("Sing", "spotify"))
    assert reg == []                                        # suena mpv
    r.sintonizar(est("Sing", "spotify"))
    reg.clear()
    r.actualizar(est("Sing", "spotify"))
    assert reg == [("spotify", "actualizar", "Sing")]
