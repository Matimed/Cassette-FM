import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
def test_logica_del_applet_con_node():
    r = subprocess.run(["node", "--test", "applet/tests/"], cwd=RAIZ, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]
