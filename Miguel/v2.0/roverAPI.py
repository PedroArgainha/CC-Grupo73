import socket
import threading
import time
from typing import Optional, Tuple

from roverINFO import Rover
import ts


class RoverAPI:

    def __init__(self, rover_id: int, nave_host: str = "127.0.0.1", nave_port: int = 6000, tick: float = 1.0):
        self.rover = Rover(rover_id, tick=tick)
        self.hostNaveMae = nave_host
        self.portoNaveMae = nave_port

        self.socketLigacao: Optional[socket.socket] = None
        self.streamLigacao = None
        self.eventoParar = threading.Event()
        self.threadEnvio: Optional[threading.Thread] = None
        self.trancaEnvio = threading.Lock()

    # ---------- controlo ----------
    def iniciar(self):
        if self.threadEnvio and self.threadEnvio.is_alive():
            return
        self.eventoParar.clear()
        self.threadEnvio = threading.Thread(target=self._cicloEnvio, daemon=True)
        self.threadEnvio.start()

    def parar(self):
        self.eventoParar.set()
        self._fecharLigacao()
        if self.threadEnvio:
            self.threadEnvio.join(timeout=1)

    # ---------- ligação TCP ----------
    def _fecharLigacao(self):
        if not self.socketLigacao:
            return
        try:
            self.socketLigacao.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.socketLigacao.close()
        except OSError:
            pass
        self.socketLigacao = None
        self.streamLigacao = None

    def _garantirLigacao(self):
        if self.socketLigacao:
            return
        while not self.eventoParar.is_set():
            try:
                self.socketLigacao = socket.create_connection((self.hostNaveMae, self.portoNaveMae), timeout=2.0)
                self.streamLigacao = self.socketLigacao.makefile("rwb", buffering=0)
                return
            except OSError:
                self._fecharLigacao()
                time.sleep(1.0)

    def _enviarDados(self, dados: bytes):
        self._garantirLigacao()
        if not self.streamLigacao:
            return
        try:
            with self.trancaEnvio:
                self.streamLigacao.write(dados)
                self.streamLigacao.flush()
        except OSError:
            self._fecharLigacao()

    # ---------- api do rover ----------
    def definirDestino(self, destino: Tuple[float, float, float]):
        self.rover.destino = destino

    def definirVelocidade(self, velocidade: float):
        self.rover.velocidade = max(0.0, velocidade)

    def _cicloEnvio(self):
        freq_hz = int(1 / self.rover.tick) if self.rover.tick > 0 else 0
        # Envia HELLO no arranque
        self._enviarDados(ts.codificarFrame(ts.TYPE_HELLO, self.rover, freq_hz))
        while not self.eventoParar.is_set():
            self.rover.iterar()
            self._enviarDados(ts.codificarFrame(ts.TYPE_INFO, self.rover, freq_hz))
            time.sleep(self.rover.tick)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rover autónomo que envia telemetria para a Nave Mãe.")
    parser.add_argument("--id", type=int, required=True, help="identificador único do rover")
    parser.add_argument("--dest", nargs=3, type=float, metavar=("X", "Y", "Z"), default=(0.0, 0.0, 0.0))
    parser.add_argument("--vel", type=float, default=0.0, help="velocidade inicial")
    parser.add_argument("--host", default="127.0.0.1", help="host da Nave Mãe")
    parser.add_argument("--port", type=int, default=6000, help="porto TCP da Nave Mãe")
    parser.add_argument("--tick", type=float, default=1.0, help="intervalo entre envios de telemetria")
    args = parser.parse_args()

    rover_api = RoverAPI(args.id, nave_host=args.host, nave_port=args.port, tick=args.tick)
    rover_api.definirDestino(tuple(args.dest))
    rover_api.definirVelocidade(args.vel)

    freq_hz = int(1 / rover_api.rover.tick) if rover_api.rover.tick > 0 else 0
    print(f"[Rover {args.id}] a enviar telemetria para {args.host}:{args.port} destino={args.dest} vel={args.vel}")
    rover_api._enviarDados(ts.codificarFrame(ts.TYPE_HELLO, rover_api.rover, freq_hz))
    try:
        while True:
            rover_api.rover.iterar()
            rover_api._enviarDados(ts.codificarFrame(ts.TYPE_INFO, rover_api.rover, freq_hz))
            time.sleep(rover_api.rover.tick)
    except KeyboardInterrupt:
        pass
    finally:
        rover_api.parar()
