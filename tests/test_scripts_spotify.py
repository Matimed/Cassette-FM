import re
import subprocess
from pathlib import Path

from cassette_fm.config import ConfigSpotify

REPO = Path(__file__).resolve().parent.parent
UNIDAD = (REPO / "packaging" / "cassette-soloist.service.in").read_text()
INSTALAR = (REPO / "scripts" / "instalar-spotify.sh").read_text()


def test_los_scripts_son_bash_valido():
    for nombre in ("instalar-spotify.sh", "actualizar-soloist.sh"):
        assert subprocess.run(["bash", "-n", str(REPO / "scripts" / nombre)]).returncode == 0, nombre


def test_la_unidad_usa_el_puerto_de_la_config_y_no_reintenta_un_build_vencido():
    puerto = ConfigSpotify().soloist_ws.rsplit(":", 1)[1]
    assert f"-w 127.0.0.1:{puerto}" in UNIDAD and "RestartPreventExitStatus=10" in UNIDAD


def test_la_key_se_lee_del_archivo_al_arrancar():
    assert '-k "$(cat "@KEY@")"' in UNIDAD


def test_el_instalador_reemplaza_todos_los_marcadores():
    marcadores = set(re.findall(r"@[A-Z_]+@", UNIDAD))
    assert marcadores and all(f"s|{m}|" in INSTALAR for m in marcadores)


def test_el_binario_va_donde_lo_busca_la_config():
    assert ConfigSpotify().soloist_bin == Path.home() / ".local/share/cassette-fm/soloist/bin/soloist"
    assert 'base="${XDG_DATA_HOME:-$HOME/.local/share}/cassette-fm/soloist"' in INSTALAR
