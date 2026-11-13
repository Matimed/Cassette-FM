import subprocess
import threading


class Notificador:
    """Notificaciones de escritorio con `notify-send`; cada aviso reemplaza al anterior."""

    def __init__(self):
        self._id: str | None = None
        self._lock = threading.Lock()
        self._hilos: list[threading.Thread] = []

    def __call__(self, estacion: str, titulo: str) -> None:
        hilo = threading.Thread(target=self._notificar, args=(estacion, titulo), daemon=True)
        self._hilos = [h for h in self._hilos if h.is_alive()] + [hilo]
        hilo.start()

    def esperar(self) -> None:
        for hilo in list(self._hilos):
            hilo.join()

    def _notificar(self, estacion: str, titulo: str) -> None:
        with self._lock:
            comando = ["notify-send", "--app-name=cassette-fm"]
            if self._id:
                comando.append(f"--replace-id={self._id}")
            comando += ["-p", estacion, titulo]
            try:
                salida = subprocess.run(comando, capture_output=True, text=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                return
            id_ = salida.stdout.strip()
            if salida.returncode == 0 and id_.isdigit():
                self._id = id_
