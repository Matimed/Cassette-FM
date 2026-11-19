import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RELAY_DIR = Path(__file__).resolve().parent.parent
TOKEN = "token-de-prueba-del-main-1234567890"
CLAVE = "clave-del-main"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sin_variables_sale_con_error():
    r = subprocess.run([sys.executable, "-m", "cassette_relay"], env={"PATH": os.environ["PATH"]},
                       cwd=RELAY_DIR, capture_output=True, text=True, timeout=10)
    assert r.returncode == 2 and "INGEST_TOKEN" in r.stderr and "error:" in r.stderr


def test_arranca_y_contesta_salud():
    puerto = _puerto_libre()
    env = {"PATH": os.environ["PATH"], "PORT": str(puerto), "INGEST_TOKEN": TOKEN, "APP_PASSWORD": CLAVE}
    proceso = subprocess.Popen([sys.executable, "-m", "cassette_relay"], env=env, cwd=RELAY_DIR,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        fin = time.monotonic() + 5
        respuesta = None
        while time.monotonic() < fin and respuesta is None:
            try:
                respuesta = urllib.request.urlopen(f"http://127.0.0.1:{puerto}/salud", timeout=1).read()
            except OSError:
                time.sleep(0.1)
        assert respuesta == b"ok"
    finally:
        proceso.terminate()
        salida, _ = proceso.communicate(timeout=10)
    assert TOKEN not in salida and CLAVE not in salida
    assert str(puerto) in salida
