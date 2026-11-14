"""Hechos verificados para las frases del DJ: clima, datos del tema (MusicBrainz)."""
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cassette_fm.dj.hechos.clima import Clima
    from cassette_fm.dj.hechos.musicbrainz import DatosTema


@dataclass(frozen=True)
class Hechos:
    """Lo verificado para un pedido; todo es opcional (sin dato, el DJ dice lo básico)."""
    clima: "Clima | None" = None
    tema: "DatosTema | None" = None
