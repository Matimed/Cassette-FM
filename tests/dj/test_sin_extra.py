import subprocess
import sys


def test_el_servicio_se_importa_sin_el_extra_dj():
    """Review: `cassette-dj` no puede romper con ModuleNotFoundError al importar si falta numpy/soundfile/kokoro."""
    codigo = (
        "import sys\n"
        "for m in ('numpy', 'soundfile', 'kokoro_onnx'):\n"
        "    sys.modules[m] = None\n"
        "import cassette_fm.dj.cli, cassette_fm.dj.servidor, cassette_fm.dj.produccion, cassette_fm.dj.sintetizador\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-I", "-c", codigo], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-500:]
