"""Escritura de archivos compartidos entre el servicio y la CLI (dos procesos a la vez)."""
import contextlib
import fcntl
import os
import tempfile
from pathlib import Path


def escribir_atomico(archivo: Path, texto: str, modo: int = 0o644) -> None:
    """Escribe en un temporal con nombre único y lo renombra: dos procesos no se pisan el temporal."""
    archivo = Path(archivo)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=archivo.parent, prefix=f".{archivo.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, modo)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        os.replace(tmp, archivo)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def bloqueado(archivo: Path):
    """Bloqueo exclusivo entre procesos (flock) sobre `<archivo>.lock`."""
    archivo = Path(archivo)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(archivo.with_name(archivo.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
