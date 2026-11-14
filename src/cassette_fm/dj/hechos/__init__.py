"""Hechos verificados para las frases del DJ: clima, datos del tema (MusicBrainz)."""
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

_log = logging.getLogger("cassette_fm")

if TYPE_CHECKING:
    from cassette_fm.dj.hechos.clima import Clima
    from cassette_fm.dj.hechos.musicbrainz import DatosTema
    from cassette_fm.dj.hechos.wikipedia import Resumen


@dataclass(frozen=True)
class Hechos:
    """Lo verificado para un pedido; todo es opcional (sin dato, el DJ dice lo básico)."""
    clima: "Clima | None" = None
    tema: "DatosTema | None" = None
    wikipedia: "Resumen | None" = None


class FuenteHechos:
    """Junta el clima y los datos del tema de un pedido, en paralelo y con tope de espera. Nunca lanza."""

    def __init__(self, clima, musicbrainz, espera_segundos: float = 6.0, wikipedia=None):
        self._clima = clima
        self._musicbrainz = musicbrainz
        self._wikipedia = wikipedia
        self._espera = espera_segundos

    def reunir(self, pedido, con_wikipedia: bool = False) -> tuple[Hechos, dict]:
        """(Hechos para redactar, `fuentes` para anotar en el guion)."""
        resultados: dict[str, object] = {}

        def pedir(nombre, funcion):
            try:
                resultados[nombre] = funcion()
            except Exception as e:                       # un cliente roto no afecta a la frase
                _log.warning("falló la consulta de %s (%s: %s): se sigue sin ese dato", nombre, type(e).__name__, e)

        hilos = []
        if self._clima is not None:
            hilos.append(threading.Thread(target=pedir, args=("clima", self._clima.actual), daemon=True,
                                          name="hechos-clima"))
        if self._musicbrainz is not None:
            s = pedido.siguiente
            hilos.append(threading.Thread(target=pedir, daemon=True, name="hechos-musicbrainz",
                                          args=("musicbrainz", lambda: self._musicbrainz.datos_del_tema(
                                              s.artista, s.titulo, s.isrc, s.album))))
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(self._espera)
        clima, tema = resultados.get("clima"), resultados.get("musicbrainz")
        wiki = None
        if con_wikipedia and self._wikipedia is not None and tema is not None and getattr(tema, "wikidata", None):
            idiomas = list(dict.fromkeys(["es" if pedido.idioma == "es" else "en", "en"]))
            hilo = threading.Thread(target=pedir, daemon=True, name="hechos-wikipedia",
                                    args=("wikipedia", lambda: self._wikipedia.resumen(tema.wikidata, idiomas)))
            hilo.start()
            hilo.join(self._espera)
            wiki = resultados.get("wikipedia")
        fuentes = {
            "clima": ({"temperatura": clima.temperatura, "cielo": clima.cielo, "es_de_dia": clima.es_de_dia}
                      if clima is not None else None),
            "musicbrainz": ({"fuente": tema.fuente, "anio": tema.anio, "pais": tema.pais,
                             "anio_inicio_artista": tema.anio_inicio_artista, "es_grupo": tema.es_grupo}
                            if tema is not None else None),
            "wikipedia": ({"url": wiki.url, "titulo": wiki.titulo, "idioma": wiki.idioma}
                          if wiki is not None else None),
        }
        return Hechos(clima, tema, wiki), fuentes
