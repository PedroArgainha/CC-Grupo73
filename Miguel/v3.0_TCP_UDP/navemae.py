import socket
import threading
from typing import Optional, Tuple

import ts

import utils as utils
import missionlink as ml
from roverINFO import Rover

from websocket_server import WebsocketServer
import json
import time



class NaveMae:

    def __init__(self,roversN: int, host: str = "0.0.0.0", port: int = 6000):
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

        # ---------- Ground Control webSockets (GC) ----------
        self.ws_server: WebsocketServer | None = None
        self.ws_client = None   # um único cliente

        # estado do rover por stream id
        self.ml_estado = {}
        i=0
        self.nRovers = roversN
        self.rovers = []
        while i<roversN:
            rover = Rover(id=i)
            self.rovers.append(rover)
            i+=1


        # ================== WEBSOCKET (GROUND CONTROL) ==================

    def start_ws_server(self, host: str = "0.0.0.0", port: int = 2900):
        server = WebsocketServer(port, host=host)
        self.ws_server = server

        server.set_fn_new_client(self._ws_novo_cliente)
        server.set_fn_client_left(self._ws_cliente_saiu)
        server.set_fn_message_received(self._ws_msg_recebida)

        print(f"[NaveMae] WebSocket em ws://{host}:{port}/")

        # Thread para o servidor WS
        t_server = threading.Thread(target=server.run_forever, daemon=True)
        t_server.start()

        # Thread para enviar updates periódicos
        t_sender = threading.Thread(target=self._ws_loop_envio, daemon=True)
        t_sender.start()

    def _ws_novo_cliente(self, client, server):
        print("[NaveMae] Ground Control ligado:", client)
        self.ws_client = client  # só um cliente

    def _ws_cliente_saiu(self, client, server):
        print("[NaveMae] Ground Control desligou-se:", client)
        if self.ws_client == client:
            self.ws_client = None

    #duvida amanha para o prof
    def _ws_msg_recebida(self, client, server, message: str):
        print("[NaveMae] Mensagem do GC (ignorada):", message)

    def _ws_loop_envio(self):
        while not self.terminar:
            self._enviar_dirty_rovers()
            time.sleep(1)

    def _enviar_dirty_rovers(self):

        if not self.ws_server or not self.ws_client:
            return
        i=0
        ficheiro = []
        while i<self.nRovers:
            if self.rovers[i].dirty:
                ficheiro.append(self.rovers[i].to_dict())
            i+=1
        if not ficheiro:
            return

        # limpa o dirty
        for r in self.rovers:
            r.dirty = False

        msg = json.dumps({"type": "rovers_update", "data": ficheiro})
        try:
            self.ws_server.send_message(self.ws_client, msg)
        except Exception as e:
            print("[NaveMae] Erro a enviar WebSocket:", e)
            self.ws_client = None



    def _ml_handle_ready(self, stream_id: int, header: ml.MLHeader, addr):
        print(f"[NaveMae/ML] READY de rover {stream_id} (seq={header.seq})")

        missao = self._ml_escolher_missao(stream_id)
        if missao is None:
            # Não há missão -> NOMISSION
            msg = ml.build_message(
                msg_type=ml.TYPE_NOMISSION,
                seq=self._prox_seq_ml(),
                ack=header.seq,          # a confirmar o READY
                stream_id=stream_id,
                payload=b"",
                flags=ml.FLAG_NEEDS_ACK,
            )
            self.ml_sock.sendto(msg, addr)
            print(f"[NaveMae/ML] → NOMISSION para rover {stream_id}")
            return

        mission_id, task_type, x, y, radius = missao
        payload = ml.build_payload_mission(mission_id, task_type, x, y, radius)

        # Guardar estado da missão
        self.ml_estado[stream_id] = {
            "mission_id": mission_id,
            "task_type": task_type,
            "target": (x, y),
            "radius": radius,
            "ultimo_progress": None,
            "done": False,
        }

        msg = ml.build_message(
            msg_type=ml.TYPE_MISSION,
            seq=self._prox_seq_ml(),
            ack=header.seq,       # piggyback ACK do READY
            stream_id=stream_id,
            payload=payload,
            flags=ml.FLAG_NEEDS_ACK,
        )
        self.ml_sock.sendto(msg, addr)
        print(f"[NaveMae/ML] → MISSION {mission_id} para rover {stream_id}")


    def _ml_handle_progress(self, stream_id: int, header: ml.MLHeader, payload: bytes, addr):
        try:
            info = ml.parse_payload_progress(payload)
        except ValueError as exc:
            print(f"[NaveMae/ML] PROGRESS inválido de rover {stream_id}: {exc}")
            return

        # Garantir entrada no dicionário
        self.ml_estado.setdefault(stream_id, {})
        self.ml_estado[stream_id]["ultimo_progress"] = info

        print(
            f"[NaveMae/ML] PROGRESS rover {stream_id}: "
            f"missao={info['mission_id']} status={info['status']} "
            f"{info['percent']}% bat={info['battery']} "
            f"pos=({info['x']:.1f},{info['y']:.1f})"
        )

        # Enviar ACK do PROGRESS
        ack_msg = ml.build_message(
            msg_type=ml.TYPE_ACK,
            seq=self._prox_seq_ml(),
            ack=header.seq,
            stream_id=stream_id,
            payload=b"",
            flags=ml.FLAG_ACK_ONLY,
        )
        self.ml_sock.sendto(ack_msg, addr)


    def _ml_handle_done(self, stream_id: int, header: ml.MLHeader, payload: bytes, addr):
        try:
            info = ml.parse_payload_done(payload)
        except ValueError as exc:
            print(f"[NaveMae/ML] DONE inválido de rover {stream_id}: {exc}")
            return

        mission_id = info["mission_id"]
        result_code = info["result_code"]

        estado = self.ml_estado.get(stream_id, {})
        estado["done"] = True
        self.ml_estado[stream_id] = estado

        print(
            f"[NaveMae/ML] DONE rover {stream_id}: "
            f"missao={mission_id} resultado={result_code}"
        )

        # ACK do DONE
        ack_msg = ml.build_message(
            msg_type=ml.TYPE_ACK,
            seq=self._prox_seq_ml(),
            ack=header.seq,
            stream_id=stream_id,
            payload=b"",
            flags=ml.FLAG_ACK_ONLY,
        )
        self.ml_sock.sendto(ack_msg, addr)


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
            #meti este comentario para melhor debug
            #print(mensagem)
            #faltaSaber como por destino
            self.rovers[hdr.id_rover].updateInfo(hdr.pos_x,hdr.pos_y,hdr.pos_z,(0,0,0),pl.velocidade,pl.direcao,hdr.bateria,hdr.state,pl.proc_use,pl.storage,pl.sensores,hdr.freq)
            return
        if tipo in (ts.TYPE_END, ts.TYPE_FIN, 3):
            print(f"[NaveMae] Rover {hdr.id_rover} desligou-se da nave ({origem})")
            return
        # fallback
        print(ts.frameParaTexto(frame, origem=origem))
    
    
    def _cicloML(self):

        print("[NaveMae/ML] Loop MissionLink iniciado.")

        while not self.terminar:
            try:
                data, addr = self.ml_sock.recvfrom(4096)
            except OSError:
                #socket foi fechado com o método parar()
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
                print(f"[NaveMae/ML] ACK de rover {sid} (ack={header.ack})")
            else:
                print(f"[NaveMae/ML] tipo de mensagem desconhecido: {msg_type} de rover {sid}")

    
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Nave Mãe minimal para frames TS.")
    parser.add_argument("--host", default="0.0.0.0", help="endereço para escutar")
    parser.add_argument("--port", type=int, default=6000, help="porto TCP para aceitar rovers")
    args = parser.parse_args()
    roversN = 6
    nave = NaveMae(roversN,args.host, args.port)
    nave.iniciar()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        nave.parar()