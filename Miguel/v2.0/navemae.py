import socket
import threading
from typing import Optional, Tuple

import ts


class NaveMae:

    def __init__(self, host: str = "0.0.0.0", port: int = 6000):
        self.host = host
        self.port = port
        self.servidorSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.servidorSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.terminar = False

    def iniciar(self):
        self.servidorSocket.bind((self.host, self.port))
        self.servidorSocket.listen()
        print(f"[NaveMae] a escutar em {self.host}:{self.port}")
        threading.Thread(target=self._cicloAceitacao, daemon=True).start()

    def parar(self):
        self.terminar = True
        try:
            self.servidorSocket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.servidorSocket.close()

    def _cicloAceitacao(self):
        while not self.terminar:
            try:
                conn, addr = self.servidorSocket.accept()
            except OSError:
                break
            threading.Thread(target=self._cicloCliente, args=(conn, addr), daemon=True).start()
            print(f"[NaveMae] ligação de {addr}")

    def _cicloCliente(self, conn: socket.socket, addr: Tuple[str, int]):
        with conn:
            conn.settimeout(1.0)
            while not self.terminar:
                cabecalho = self._receberExacto(conn, ts.HEADER_SIZE)
                if not cabecalho:
                    break
                try:
                    cabecalhoLido = ts.lerHeader(cabecalho)
                    dadosPayload = self._receberExacto(conn, cabecalhoLido.payload_len)
                    if dadosPayload is None:
                        break
                    frame = ts.decodificarFrame(cabecalho, dadosPayload)
                    self._imprimir(frame, addr)
                except Exception as exc:  # noqa: BLE001
                    print(f"[NaveMae] erro {addr}: {exc}")
                    break
        print(f"[NaveMae] ligação terminada {addr}")

    def _receberExacto(self, conn: socket.socket, n: int) -> Optional[bytes]:
        data = bytearray()
        while len(data) < n and not self.terminar:
            try:
                chunk = conn.recv(n - len(data))
            except socket.timeout:
                continue
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data) if len(data) == n else None

    def _imprimir(self, frame: ts.Frame, addr: Tuple[str, int]):
        hdr, pl = frame.header, frame.payload
        origem = f"{addr[0]}:{addr[1]}"
        tipo = hdr.tipo
        if tipo in (ts.TYPE_HELLO, 1):
            print(f"[NaveMae] Rover {hdr.id_rover} ligou-se à nave ({origem})")
            return
        if tipo == ts.TYPE_INFO:
            mensagem = (
                f"[NaveMae] Rover {hdr.id_rover}:\n"
                f"  -> loc=({hdr.pos_x},{hdr.pos_y},{hdr.pos_z}) freq={hdr.freq}/s\n"
                f"  -> bat={hdr.bateria}% estado={hdr.state}\n"
                f"  -> proc={pl.proc_use} storage={pl.storage} vel={pl.velocidade} dir={pl.direcao} sens={pl.sensores}"
            )
            print(mensagem)
            return
        if tipo in (ts.TYPE_END, ts.TYPE_FIN, 3):
            print(f"[NaveMae] Rover {hdr.id_rover} desligou-se da nave ({origem})")
            return
        # fallback
        print(ts.frameParaTexto(frame, origem=origem))


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description="Nave Mãe minimal para frames TS.")
    parser.add_argument("--host", default="0.0.0.0", help="endereço para escutar")
    parser.add_argument("--port", type=int, default=6000, help="porto TCP para aceitar rovers")
    args = parser.parse_args()

    nave = NaveMae(args.host, args.port)
    nave.iniciar()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        nave.parar()
