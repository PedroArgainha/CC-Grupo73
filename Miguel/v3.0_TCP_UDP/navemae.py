import socket
import threading
from typing import Optional, Tuple

import ts

import missionlink as ml


class NaveMae:

    def __init__(self, host: str = "0.0.0.0", port: int = 6000):
        self.host = host
        self.port = port
       
        # ---------- Telemetria (TCP) ----------
        self.servidorSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.servidorSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.terminar = False


        # ---------- Mission Link (UDP) ----------
        self.ml_port = 50000                      # porto UDP para o ML
        self.ml_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ml_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ml_thread: Optional[threading.Thread] = None
        self.ml_seq = 1 #numero de sequência global

        # estado do rover por stream id
        self.ml_estado = {}




    def iniciar(self):
        
        # ---- Telemetria (TCP) ----
        self.servidorSocket.bind((self.host, self.port))
        self.servidorSocket.listen()
        print(f"[NaveMae] a escutar em {self.host}:{self.port}")
        threading.Thread(target=self._cicloAceitacao, daemon=True).start()

        # ---- Mission Link (UDP) ----
        self.ml_sock.bind((self.host, self.ml_port))
        print(f"[NaveMae] a escutar ML (UDP) em {self.host}:{self.ml_port}")
        self.ml_thread = threading.Thread(target=self._cicloML, daemon=True)
        self.ml_thread.start()


    def parar(self):
        self.terminar = True

        # --- fechar TCP (telemetria) ---
        try:
            self.servidorSocket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.servidorSocket.close()

        # --- fechar UDP (MissionLink) ---
        try:
            self.ml_sock.close()
        except OSError:
            pass

        if self.ml_thread and self.ml_thread.is_alive():
            self.ml_thread.join(timeout=1.0)



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
    
    
        def _cicloML(self):
                """
    Loop principal do protocolo MissionLink (UDP) na Nave-Mãe.

    - Recebe READY dos rovers
    - Envia MISSION ou NOMISSION
    - Recebe PROGRESS e DONE
    - Envia ACKs
         """
        print("[NaveMae/ML] Loop MissionLink iniciado.")

        while not self.terminar:
            try:
                data, addr = self.ml_sock.recvfrom(4096)
            except OSError:
                break

            try:
                header, payload = ml.parse_message(data)
            except ValueError as exc:
                print(f"[NaveMae/ML] mensagem inválida de {addr}: {exc}")
                continue

            sid = header.stream_id   # id lógico do rover
            msg_type = header.msg_type

            if msg_type == ml.TYPE_READY:
                self._ml_handle_ready(sid, header, addr)
            elif msg_type == ml.TYPE_PROGRESS:
                self._ml_handle_progress(sid, header, payload, addr)
            elif msg_type == ml.TYPE_DONE:
                self._ml_handle_done(sid, header, payload, addr)
            elif msg_type == ml.TYPE_ACK:
                # para já não estamos a usar ACKs do lado da Mãe,
                # mas podes guardar se quiseres.
                print(f"[NaveMae/ML] ACK de rover {sid} (ack={header.ack})")
            else:
                print(f"[NaveMae/ML] tipo de mensagem desconhecido: {msg_type} de rover {sid}")

    







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


