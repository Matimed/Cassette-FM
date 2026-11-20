"""La aplicación aiohttp: rutas de la PC (`/casa/…`), de los oyentes (`/api/…`), la página y `/salud`."""
from pathlib import Path

from aiohttp import web

from .acceso import Acceso
from .api import Api
from .casa import MAX_LOGO, Casa
from .config import Ajustes
from .oyentes import Oyentes

CASA = web.AppKey("casa", Casa)
OYENTES = web.AppKey("oyentes", Oyentes)
ACCESO = web.AppKey("acceso", Acceso)
AJUSTES = web.AppKey("ajustes", Ajustes)

WEB_POR_DEFECTO = Path(__file__).resolve().parent.parent / "web"


async def _salud(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def crear_app(ajustes: Ajustes, web_dir: Path | None = None) -> web.Application:
    app = web.Application(client_max_size=MAX_LOGO + 64 * 1024)
    casa: Casa | None = None
    oyentes = Oyentes(lambda calidades: casa.mandar_demanda(calidades), gracia=ajustes.gracia,
                      cola_segundos=ajustes.cola_segundos)
    acceso = Acceso(ajustes.clave_maestra)

    def aplicar_claves(claves: list[dict]) -> None:
        acceso.poner_claves(claves)
        oyentes.cortar_fuera({c["id"] for c in claves})        # una clave borrada deja de escuchar en el acto

    casa = Casa(ajustes, oyentes, al_recibir_claves=aplicar_claves)
    app[CASA] = casa
    app[OYENTES] = oyentes
    app[ACCESO] = acceso
    app[AJUSTES] = ajustes

    async def al_cerrar(app: web.Application) -> None:
        await casa.cerrar()
    app.on_shutdown.append(al_cerrar)

    app.router.add_get("/salud", _salud)
    app.router.add_get("/casa/control", casa.control)
    app.router.add_get("/casa/audio", casa.audio)
    app.router.add_put("/casa/icono/{nombre:.+}", casa.subir_icono)
    Api(ajustes, casa, oyentes, app[ACCESO]).rutas(app)

    carpeta = web_dir or WEB_POR_DEFECTO

    async def pagina(request: web.Request) -> web.FileResponse:
        return web.FileResponse(carpeta / "index.html", headers={"Cache-Control": "no-cache"})
    app.router.add_get("/", pagina)

    async def favicon(request: web.Request) -> web.FileResponse:     # los navegadores lo piden solos, sin mirar el <link>
        return web.FileResponse(carpeta / "favicon-32.png", headers={"Cache-Control": "public, max-age=86400"})
    app.router.add_get("/favicon.ico", favicon)
    if carpeta.is_dir():
        app.router.add_static("/web", carpeta)
    return app
