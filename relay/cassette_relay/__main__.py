"""`python -m cassette_relay`: lee la configuración del entorno y atiende en 0.0.0.0:$PORT."""
import logging
import os
import sys

from aiohttp import web

from .app import crear_app
from .config import ErrorConfig, desde_entorno


def main() -> int:
    try:
        ajustes = desde_entorno(os.environ)
    except ErrorConfig as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("cassette_relay").info("relay escuchando en el puerto %d", ajustes.puerto)
    web.run_app(crear_app(ajustes), host="0.0.0.0", port=ajustes.puerto, access_log=None, print=None,
                shutdown_timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
