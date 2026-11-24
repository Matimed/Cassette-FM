"""Los instaladores de scripts/: cada uno deja un componente completo y pide lo que necesita (y nada más).

Se corren de verdad, pero en una copia del proyecto con `systemctl`, `pip`, `cassette`, `cassette-dj` y compañía reemplazados por
stubs que anotan lo que les piden, y con HOME y los XDG en una carpeta temporal: no tocan el sistema."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"

STUB_ANOTADOR = '#!/bin/sh\necho "{nombre} $*" >> "$LOG"\n'
STUB_SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >> "$LOG"
if [ "$1 $2" = "--user cat" ]; then [ -e "$XDG_CONFIG_HOME/systemd/user/$3.service" ]; fi
"""
STUB_SOLOIST_INSTALADOR = """#!/usr/bin/env bash
echo "actualizar-soloist $*" >> "$LOG"
base="$XDG_DATA_HOME/cassette-fm/soloist"
mkdir -p "$base/bin"
printf '#!/bin/sh\\necho "soloist $*" >> "$LOG"\\n' > "$base/bin/soloist"
chmod +x "$base/bin/soloist"
"""


def _escribir(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto)
    ruta.chmod(0o755)


class Entorno:
    """Un proyecto falso (los scripts y las plantillas reales) y un HOME vacío."""

    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.repo = raiz / "proyecto"
        self.home = raiz / "home"
        self.log = raiz / "log.txt"
        shutil.copytree(SCRIPTS, self.repo / "scripts", ignore=shutil.ignore_patterns("__pycache__", "herramientas"))
        shutil.copytree(REPO / "packaging", self.repo / "packaging")
        for nombre in ("cassette", "cassette-dj", "pip", "python"):
            _escribir(self.repo / ".venv" / "bin" / nombre, STUB_ANOTADOR.format(nombre=nombre))
        stubs = raiz / "stubs"
        _escribir(stubs / "systemctl", STUB_SYSTEMCTL)
        for nombre in ("mpv", "pactl", "gsettings", "curl"):
            _escribir(stubs / nombre, STUB_ANOTADOR.format(nombre=nombre))
        self.env = {**os.environ, "HOME": str(self.home), "LOG": str(self.log), "PATH": f"{stubs}:{os.environ['PATH']}",
                    "XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_DATA_HOME": str(self.home / ".local/share"),
                    "XDG_STATE_HOME": str(self.home / ".local/state"), "XDG_CACHE_HOME": str(self.home / ".cache")}
        self.home.mkdir()
        self.log.write_text("")

    def correr(self, script: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.repo / "scripts" / script), *args], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def llamadas(self) -> list[str]:
        return self.log.read_text().splitlines()

    @property
    def unidades(self) -> Path:
        return self.home / ".config" / "systemd" / "user"

    @property
    def config_radio(self) -> Path:
        return self.home / ".config" / "cassette-fm" / "config.toml"

    @property
    def dropin_bus(self) -> Path:
        return self.unidades / "cassette-soloist.service.d" / "bus-audio.conf"

    def con_radio(self) -> "Entorno":
        self.unidades.mkdir(parents=True, exist_ok=True)
        (self.unidades / "cassette-fm.service").write_text("[Service]\n")
        return self

    def con_key_de_soloist(self) -> "Entorno":
        key = self.home / ".config" / "cassette-fm" / "soloist.key"
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text("clave-de-prueba\n")
        return self

    def con_soloist_instalado(self) -> "Entorno":
        (self.unidades / "cassette-soloist.service").write_text("[Service]\n")
        return self

    def con_sesion_de_spotify(self) -> "Entorno":
        token = self.home / ".local" / "state" / "cassette-fm" / "spotify-token.json"
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_text("{}")
        return self


@pytest.fixture
def entorno(tmp_path):
    return Entorno(tmp_path)


def test_todos_los_scripts_de_shell_son_bash_valido():
    scripts = sorted(SCRIPTS.glob("*.sh")) + [SCRIPTS / "lib" / "comun.sh"]
    assert len(scripts) >= 9
    for script in scripts:
        assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0, script.name
        if script.parent == SCRIPTS:
            assert script.stat().st_mode & 0o111, f"{script.name} no es ejecutable"
            assert "set -euo pipefail" in script.read_text(), script.name


# --- radio ---

def test_la_radio_se_instala_sola_y_deja_el_servicio_andando(entorno):
    r = entorno.correr("instalar-radio.sh")
    assert r.returncode == 0, r.stderr
    unidad = (entorno.unidades / "cassette-fm.service").read_text()
    assert f"ExecStart={entorno.repo}/.venv/bin/cassette serve" in unidad and "@" not in unidad
    assert (entorno.home / ".local/bin/cassette").resolve() == (entorno.repo / ".venv/bin/cassette").resolve()
    llamadas = entorno.llamadas()
    assert f"pip install -q -e {entorno.repo}" in llamadas
    assert "systemctl --user enable cassette-fm" in llamadas
    # reiniciar y no solo arrancar: una radio ya levantada sigue con el código viejo
    assert "systemctl --user restart cassette-fm" in llamadas
    assert "cassette status" in llamadas, "tiene que comprobar que el servicio responde"
    assert not (entorno.dropin_bus.parent).exists() and not (entorno.home / ".config/cassette-fm").exists()


def test_la_radio_no_instala_nada_del_escritorio(entorno):
    entorno.correr("instalar-radio.sh")
    llamadas = entorno.llamadas()
    assert "cassette atajos" not in llamadas and "cassette applet" not in llamadas


# --- escritorio ---

def test_el_escritorio_pide_la_radio_y_no_toca_nada_sin_ella(entorno):
    r = entorno.correr("instalar-escritorio.sh")
    assert r.returncode != 0 and "instalar-radio.sh" in r.stderr
    assert entorno.llamadas() == []


def test_el_escritorio_registra_atajos_y_applet(entorno):
    entorno.con_radio()
    r = entorno.correr("instalar-escritorio.sh")
    assert r.returncode == 0, r.stderr
    assert entorno.llamadas() == ["cassette atajos", "cassette applet"]
    assert "Ctrl+Alt+Esc" in r.stdout


# --- base: la radio y el escritorio juntos ---

def test_la_base_son_la_radio_y_el_escritorio_en_ese_orden(entorno):
    r = entorno.correr("instalar-base.sh")
    assert r.returncode == 0, r.stderr
    llamadas = entorno.llamadas()
    assert llamadas.index("systemctl --user restart cassette-fm") < llamadas.index("cassette atajos") \
        < llamadas.index("cassette applet")


# --- spotify ---

def test_spotify_pide_la_radio(entorno):
    entorno.con_key_de_soloist()
    r = entorno.correr("instalar-spotify.sh")
    assert r.returncode != 0 and "instalar-radio.sh" in r.stderr
    assert entorno.llamadas() == []


def test_spotify_pide_la_key_antes_de_bajar_nada(entorno):
    entorno.con_radio()
    r = entorno.correr("instalar-spotify.sh")
    assert r.returncode != 0 and "soloist.key" in r.stderr
    assert entorno.llamadas() == []


def _spotify_listo(entorno: Entorno) -> Entorno:
    """Con la radio y la key, y el instalador del binario reemplazado por un stub (el real baja de internet)."""
    entorno.con_radio().con_key_de_soloist()
    _escribir(entorno.repo / "scripts" / "actualizar-soloist.sh", STUB_SOLOIST_INSTALADOR)
    return entorno


def test_spotify_queda_completo_en_un_solo_script(entorno):
    r = _spotify_listo(entorno).correr("instalar-spotify.sh")
    assert r.returncode == 0, r.stderr
    unidad = (entorno.unidades / "cassette-soloist.service").read_text()
    assert "@" not in unidad and "soloist.key" in unidad
    # el audio de Soloist va al bus sin pasar por otro script
    dropin = entorno.dropin_bus.read_text()
    assert "PIPEWIRE_NODE=radio_virtual" in dropin and "PartOf=cassette-fm.service" in dropin
    llamadas = entorno.llamadas()
    assert "systemctl --user enable cassette-soloist" in llamadas
    assert "cassette spotify login" in llamadas
    assert any(" --pair" in x for x in llamadas), "primero se empareja"
    # el login y el emparejamiento se hacen antes de reiniciar, y la radio y Soloist se reinician juntos
    reinicio = llamadas.index("systemctl --user restart cassette-fm cassette-soloist")
    assert llamadas.index("cassette spotify login") < reinicio
    assert reinicio < len(llamadas) and "cassette status" in llamadas[reinicio:]


def test_spotify_no_vuelve_a_emparejar_ni_a_loguear_si_ya_esta_hecho(entorno):
    _spotify_listo(entorno).con_sesion_de_spotify()
    settings = entorno.home / ".local/share/cassette-fm/soloist/datos/settings"
    settings.parent.mkdir(parents=True)
    settings.write_text("")
    assert entorno.correr("instalar-spotify.sh").returncode == 0
    llamadas = entorno.llamadas()
    assert "cassette spotify login" not in llamadas and not any(" --pair" in x for x in llamadas)


def test_spotify_sin_bus_no_dirige_soloist_al_bus(entorno):
    _spotify_listo(entorno).con_sesion_de_spotify()
    entorno.config_radio.write_text("bus_audio = false\n")
    r = entorno.correr("instalar-spotify.sh")
    assert r.returncode == 0, r.stderr
    assert not entorno.dropin_bus.exists() and "bus_audio = false" in r.stdout


# --- bus de audio ---

def test_el_bus_pide_la_radio(entorno):
    r = entorno.correr("bus-audio.sh", "quitar")
    assert r.returncode != 0 and "instalar-radio.sh" in r.stderr


def test_el_bus_rechaza_una_accion_desconocida(entorno):
    entorno.con_radio()
    r = entorno.correr("bus-audio.sh", "borrar")
    assert r.returncode != 0 and "Uso:" in r.stderr and entorno.llamadas() == []


def test_quitar_y_activar_el_bus_cambian_la_config_y_el_enrutado_de_soloist(entorno):
    entorno.con_radio().con_soloist_instalado()
    assert entorno.correr("bus-audio.sh").returncode == 0                       # activar es lo de fábrica
    assert entorno.config_radio.read_text() == "bus_audio = true\n" and entorno.dropin_bus.exists()
    assert "systemctl --user restart cassette-fm cassette-soloist" in entorno.llamadas()
    assert entorno.correr("bus-audio.sh", "quitar").returncode == 0
    assert entorno.config_radio.read_text() == "bus_audio = false\n" and not entorno.dropin_bus.exists()
    assert entorno.correr("bus-audio.sh", "quitar").returncode == 0             # idempotente
    assert entorno.config_radio.read_text().count("bus_audio") == 1


def test_el_bus_sin_soloist_no_inventa_enrutado_ni_reinicia_lo_que_no_hay(entorno):
    entorno.con_radio()
    entorno.config_radio.parent.mkdir(parents=True)
    entorno.config_radio.write_text('puerto = 7711\n\n[dj]\nactivo = true\n')
    assert entorno.correr("bus-audio.sh", "quitar").returncode == 0
    texto = entorno.config_radio.read_text()
    assert texto.startswith("bus_audio = false\n") and "puerto = 7711" in texto and "[dj]" in texto
    assert not entorno.dropin_bus.parent.exists()
    assert "systemctl --user restart cassette-fm" in entorno.llamadas()
    assert not any("cassette-soloist" in x for x in entorno.llamadas())


# --- DJ ---

def test_el_dj_se_instala_solo_sin_la_radio_y_baja_sus_modelos_antes_de_arrancar(entorno):
    r = entorno.correr("instalar-dj.sh")
    assert r.returncode == 0, r.stderr
    llamadas = entorno.llamadas()
    assert f"pip install -q -e {entorno.repo}[dj,piper]" in llamadas
    assert (entorno.home / ".local/bin/cassette-dj").is_symlink()
    unidad = (entorno.unidades / "cassette-dj.service").read_text()
    assert f"ExecStart={entorno.repo}/.venv/bin/cassette-dj serve" in unidad and "@" not in unidad
    assert llamadas.index("cassette-dj modelos") < llamadas.index("systemctl --user restart cassette-dj")
    assert "systemctl --user enable cassette-dj" in llamadas
    assert any("127.0.0.1:7720/salud" in x for x in llamadas), "tiene que comprobar que el servicio responde"
    assert not (entorno.unidades / "cassette-fm.service").exists()


def test_el_dj_baja_las_voces_de_piper_que_se_le_pidan(entorno):
    r = entorno.correr("instalar-dj.sh", "--voz-piper", "es_AR-daniela-high", "--voz-piper", "es_MX-claude-high")
    assert r.returncode == 0, r.stderr
    destino = entorno.home / ".local/share/cassette-dj/modelos/piper"
    llamadas = entorno.llamadas()
    for voz in ("es_AR-daniela-high", "es_MX-claude-high"):
        assert f"python -m piper.download_voices --download-dir {destino} {voz}" in llamadas
    assert llamadas.index("cassette-dj modelos") < llamadas.index(
        f"python -m piper.download_voices --download-dir {destino} es_AR-daniela-high") \
        < llamadas.index("systemctl --user restart cassette-dj")


def test_el_dj_rechaza_argumentos_mal_puestos_sin_instalar_nada(entorno):
    for args in (["--voz-piper"], ["--otra-cosa"]):
        r = entorno.correr("instalar-dj.sh", *args)
        assert r.returncode != 0 and r.stderr
    assert entorno.llamadas() == []


# --- mantenimiento de Soloist ---

def test_actualizar_soloist_sin_servicio_no_falla_y_dice_como_instalarlo(entorno):
    """El binario real baja de internet: se reemplaza `curl` y `tar` para ver solo qué hace con el servicio."""
    stubs = entorno.raiz / "stubs"
    _escribir(stubs / "curl", '#!/bin/sh\nwhile [ "$#" -gt 0 ]; do [ "$1" = "-o" ] && { : > "$2"; break; }; shift; done\n')
    _escribir(stubs / "tar", '#!/bin/sh\nwhile [ "$#" -gt 0 ]; do [ "$1" = "-C" ] && { '
              'printf "#!/bin/sh\\necho soloist-falso\\n" > "$2/soloist"; chmod +x "$2/soloist"; break; }; shift; done\n')
    if os.uname().machine != "x86_64":
        pytest.skip("el script solo baja Soloist para x86_64")
    r = entorno.correr("actualizar-soloist.sh")
    assert r.returncode == 0, r.stderr
    assert "instalar-spotify.sh" in r.stdout and "restart cassette-soloist" not in " ".join(entorno.llamadas())
