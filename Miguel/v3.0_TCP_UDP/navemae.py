import socket
import threading
from typing import Optional, Tuple

import ts
from missoes import int_to_mission

import utils as utils
import missionlink as ml
from roverINFO import Rover
from mission_scenarios import generate_missions

from websocket_server import WebsocketServer
import json
import time
import argparse


class NaveMae:

    def __init__(self, roversN: int, host: str = "0.0.0.0", port: int = 6000, scenario: int = 2):
        self.host = host
        self.port = port

        # ---------- Telemetria (TCP) ----------
        self.servidorSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.servidorSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.terminar = False

        # ---------- Mission Link (UDP) ----------
        self.ml_port = 50000
        self.ml_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ml_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ml_thread: Optional[threading.Thread] = None
        self.ml_seq = 1  # numero de sequência global

        # ---------- Ground Control webSockets (GC) ----------
        self.ws_server: WebsocketServer | None = None
        self.ws_client = None  # um único cliente

        # estado do rover por stream id
        self.ml_estado = {}
        self.ml_last_seq = {}

        self.nRovers = roversN
        self.rovers = []
        for i in range(roversN):
            self.rovers.append(Rover(id=i + 1))

        self.scenario = scenario
        self.missions_pending = generate_missions(scenario)
        self.missions_assigned = {}
        self.missions_done = []

        if scenario == 3:
            self.rr_idx = 0

    # ================== MissionLink helpers ==================

    def _prox_seq_ml(self) -> int:
        """Devolve o seq atual e incrementa-o."""
        s = self.ml_seq
        self.ml_seq += 1
        return s

    # ================== WEBSOCKET (GROUND CONTROL) ==================

    def start_ws_server(self, host: str = "0.0.0.0", port: int = 2900):
        server = WebsocketServer(host=host, port=port)
        self.ws_server = server

        server.set_fn_new_client(self._ws_novo_cliente)
        server.set_fn_client_left(self._ws_cliente_saiu)
        server.set_fn_message_received(self._ws_msg_recebida)

        print(f"[NaveMae] WebSocket em ws://{host}:{port}/")

        t_server = threading.Thread(target=server.run_forever, daemon=True)
        t_server.start()

        t_sender = threading.Thread(target=self._ws_loop_envio, daemon=True)
        t_sender.start()

    def _ws_novo_cliente(self, client, server):
        print("[NaveMae] Ground Control ligado:", client)
        self.ws_client = client  # só um cliente

    def _ws_cliente_saiu(self, client, server):
        print("[NaveMae] Ground Control desligou-se:", client)
        if self.ws_client == client:
            self.ws_client = None

    def _ws_msg_recebida(self, client, server, message: str):
        # Atualmente ignoramos comandos do GC
        print("[NaveMae] Mensagem do GC (ignorada):", message)

    def _ws_loop_envio(self):
        while not self.terminar:
            self._enviar_dirty_rovers()
            time.sleep(1)

    def _enviar_dirty_rovers(self):
        if not self.ws_server or not self.ws_client:
            return

        updates = []
        for i in range(self.nRovers):
            if self.rovers[i].dirty:
                updates.append(self.rovers[i].to_dict())

        if not updates:
            # podes comentar este print se te chatear
            # print("[NaveMae] Nenhum rover dirty, nada para enviar")
            return

        # limpa o dirty
        for r in self.rovers:
            r.dirty = False

        msg = json.dumps({"type": "rovers_update", "data": updates})
        try:
            self.ws_server.send_message(self.ws_client, msg)
        except Exception as e:
            print("[NaveMae] Erro a enviar WebSocket:", e)
            self.ws_client = None
        # finally:
        #     print("Enviei JSON")

    # ================== Missões (escolha/atribuição) ==================

    def _ml_escolher_missao(self, stream_id: int):
        # Se já tem missão (retransmissões)
        if stream_id in self.missions_assigned:
            m = self.missions_assigned[stream_id]
            return (m["mission_id"], m["task_type"], m["x"], m["y"], m["radius"], m["duracao"])

        # Round-robin
        if self.scenario == 3:
            if not self.missions_pending:
                return None

            assigned_ids = {m["mission_id"] for m in self.missions_assigned.values()}

            for _ in range(len(self.missions_pending)):
                m = self.missions_pending[self.rr_idx]
                self.rr_idx = (self.rr_idx + 1) % len(self.missions_pending)

                if m["mission_id"] not in assigned_ids:
                    self.missions_assigned[stream_id] = m
                    return (m["mission_id"], m["task_type"], m["x"], m["y"], m["radius"], m["duracao"])

            return None

        # Cenários finitos
        if not self.missions_pending:
            return None

        m = self.missions_pending.pop(0)
        self.missions_assigned[stream_id] = m
        return (m["mission_id"], m["task_type"], m["x"], m["y"], m["radius"], m["duracao"])

    # ================== MissionLink handlers ==================

    def _ml_is_duplicate(self, stream_id: int, header: ml.MLHeader) -> bool:
        """Deduplicação por seq (usar para PROGRESS)."""
        last = self.ml_last_seq.get(stream_id)

        if last is None:
            self.ml_last_seq[stream_id] = header.seq
            return False

        if header.seq > last:
            self.ml_last_seq[stream_id] = header.seq
            return False

        return True

    def _ml_handle_ready(self, stream_id: int, header: ml.MLHeader, addr):
        print(f"[NaveMae/ML] READY de rover {stream_id} (seq={header.seq})")

        missao = self._ml_escolher_missao(stream_id)

        if missao is None:
            msg = ml.build_message(
                msg_type=ml.TYPE_NOMISSION,
                seq=self._prox_seq_ml(),
                ack=header.seq,
                stream_id=stream_id,
                payload=b"",
                flags=ml.FLAG_NEEDS_ACK,
            )
            self.ml_sock.sendto(msg, addr)
            print(f"[NaveMae/ML] → NOMISSION para rover {stream_id}")
            return

        # missao = (mission_id, task_type, x, y, radius, duracao)
        mission_id, task_type, x, y, radius, duracao = missao

        payload = ml.build_payload_mission(mission_id, task_type, x, y, radius, duracao)

        # Guardar estado interno da missão para este rover
        self.ml_estado[stream_id] = {
            "mission_id": mission_id,
            "task_type": task_type,
            "target": (x, y),
            "radius": radius,
            "duracao": duracao,
            "ultimo_progress": None,
            "done": False,
        }

        # >>> CORREÇÃO PRINCIPAL: guardar mission_id separado do task_type
        rover_idx = stream_id - 1
        if 0 <= rover_idx < self.nRovers:
            self.rovers[rover_idx].mission_id = mission_id
            self.rovers[rover_idx].atribiuMission(task_type)
            # marca dirty para o GC receber update imediato
            self.rovers[rover_idx].dirty = True

        print(
            f"\033[91m[Nave-Mãe] "
            f"Atribui missão ID={mission_id} | "
            f"TaskType={task_type} ({int_to_mission(task_type)}) "
            f"ao rover {stream_id}\033[0m"
        )

        msg = ml.build_message(
            msg_type=ml.TYPE_MISSION,
            seq=self._prox_seq_ml(),
            ack=header.seq,
            stream_id=stream_id,
            payload=payload,
            flags=ml.FLAG_NEEDS_ACK,
        )
        self.ml_sock.sendto(msg, addr)
        print(f"[NaveMae/ML] → MISSION {mission_id} para rover {stream_id} (duracao={duracao})")

    def _ml_handle_progress(self, stream_id: int, header: ml.MLHeader, payload: bytes, addr):
        try:
            info = ml.parse_payload_progress(payload)
        except ValueError as exc:
            print(f"[NaveMae/ML] PROGRESS inválido de rover {stream_id}: {exc}")
            return

        mission_id = info["mission_id"]
        estado = self.ml_estado.get(stream_id)

        # Missão inválida / fora de contexto -> ACK para parar retransmissões
        if not estado or estado.get("mission_id") != mission_id:
            print(
                f"[NaveMae/ML] PROGRESS fora de contexto de rover {stream_id}: "
                f"missao={mission_id} (sem missão ativa correspondente)"
            )
            ack_msg = ml.build_message(
                msg_type=ml.TYPE_ACK,
                seq=self._prox_seq_ml(),
                ack=header.seq,
                stream_id=stream_id,
                payload=b"",
                flags=ml.FLAG_ACK_ONLY,
            )
            self.ml_sock.sendto(ack_msg, addr)
            return

        # Dedup por seq
        if self._ml_is_duplicate(stream_id, header):
            ack_msg = ml.build_message(
                msg_type=ml.TYPE_ACK,
                seq=self._prox_seq_ml(),
                ack=header.seq,
                stream_id=stream_id,
                payload=b"",
                flags=ml.FLAG_ACK_ONLY,
            )
            self.ml_sock.sendto(ack_msg, addr)
            return

        estado["ultimo_progress"] = info
        self.ml_estado[stream_id] = estado

        # Se quiseres refletir progresso no rover local (para o GC), podes atualizar aqui
        rover_idx = stream_id - 1
        if 0 <= rover_idx < self.nRovers:
            self.rovers[rover_idx].progresso = info["percent"]
            self.rovers[rover_idx].dirty = True

        print(
            f"[NaveMae/ML] PROGRESS rover {stream_id}: "
            f"missao={info['mission_id']} status={info['status']} "
            f"{info['percent']}% bat={info['battery']} "
            f"pos=({info['x']:.1f},{info['y']:.1f})"
        )

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

        estado = self.ml_estado.get(stream_id)

        if not estado or estado.get("mission_id") != mission_id:
            print(
                f"[NaveMae/ML] DONE fora de contexto de rover {stream_id}: "
                f"missao={mission_id} (sem missão ativa correspondente)"
            )
            ack_msg = ml.build_message(
                msg_type=ml.TYPE_ACK,
                seq=self._prox_seq_ml(),
                ack=header.seq,
                stream_id=stream_id,
                payload=b"",
                flags=ml.FLAG_ACK_ONLY,
            )
            self.ml_sock.sendto(ack_msg, addr)
            return

        if estado.get("done"):
            ack_msg = ml.build_message(
                msg_type=ml.TYPE_ACK,
                seq=self._prox_seq_ml(),
                ack=header.seq,
                stream_id=stream_id,
                payload=b"",
                flags=ml.FLAG_ACK_ONLY,
            )
            self.ml_sock.sendto(ack_msg, addr)
            return

        estado["done"] = True
        self.ml_estado[stream_id] = estado

        print(f"[NaveMae/ML] DONE rover {stream_id}: missao={mission_id} resultado={result_code}")

        ack_msg = ml.build_message(
            msg_type=ml.TYPE_ACK,
            seq=self._prox_seq_ml(),
            ack=header.seq,
            stream_id=stream_id,
            payload=b"",
            flags=ml.FLAG_ACK_ONLY,
        )
        self.ml_sock.sendto(ack_msg, addr)

        # Libertar missão (evita repetir no scenario 2)
        m = self.missions_assigned.pop(stream_id, None)
        if m is not None:
            self.missions_done.append(m)

        # Limpar estado do rover local (para GC)
        rover_idx = stream_id - 1
        if 0 <= rover_idx < self.nRovers:
            self.rovers[rover_idx].missao = 0
            self.rovers[rover_idx].mission_id = 0
            self.rovers[rover_idx].progresso = 0
            self.rovers[rover_idx].dirty = True

    # ================== Start/Stop ==================

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

        # ---- GC WebSocket ----
        self.start_ws_server(host=self.host, port=2900)

    def parar(self):
        self.terminar = True

        # fechar TCP
        try:
            self.servidorSocket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.servidorSocket.close()

        # fechar UDP
        try:
            self.ml_sock.close()
        except OSError:
            pass

        if self.ml_thread and self.ml_thread.is_alive():
            self.ml_thread.join(timeout=1.0)

    # ================== Telemetria TCP (TS) ==================

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
                except Exception as exc:
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
            realIndex = hdr.id_rover - 1
            if 0 <= realIndex < self.nRovers:
                # passa também o mission_id atual (não mistura com task_type)
                current_mission_id = getattr(self.rovers[realIndex], "mission_id", 0)

                self.rovers[realIndex].updateInfo(
                    hdr.pos_x, hdr.pos_y, hdr.pos_z,
                    (0, 0, 0),                 # destino ainda não está no TS payload no teu código
                    pl.velocidade, pl.direcao,
                    hdr.bateria, hdr.state,
                    pl.proc_use, pl.storage,
                    pl.sensores, hdr.freq,
                    self.rovers[realIndex].missao,
                    pl.progresso,
                    mission_id=current_mission_id
                )

                # marca dirty para GC ver telemetria atualizada
                self.rovers[realIndex].dirty = True

            print(f"Recebi Rover {hdr.id_rover}\n")
            return

        if tipo in (ts.TYPE_END, ts.TYPE_FIN, 3):
            print(f"[NaveMae] Rover {hdr.id_rover} desligou-se da nave ({origem})")
            return

        print(ts.frameParaTexto(frame, origem=origem))

    # ================== MissionLink loop ==================

    def _cicloML(self):
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

            sid = header.stream_id
            msg_type = header.msg_type

            if msg_type == ml.TYPE_READY:
                self._ml_handle_ready(sid, header, addr)
            elif msg_type == ml.TYPE_PROGRESS:
                self._ml_handle_progress(sid, header, payload, addr)
            elif msg_type == ml.TYPE_DONE:
                self._ml_handle_done(sid, header, payload, addr)
            elif msg_type == ml.TYPE_ACK:
                print(f"[NaveMae/ML] ACK de rover {sid} (ack={header.ack})")
            else:
                print(f"[NaveMae/ML] tipo de mensagem desconhecido: {msg_type} de rover {sid}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nave Mãe minimal para frames TS.")
    parser.add_argument("--host", default="0.0.0.0", help="endereço para escutar")
    parser.add_argument("--port", type=int, default=6000, help="porto TCP para aceitar rovers")
    parser.add_argument("--scenario", type=int, default=2, help="0=sem missoes | 1=1 missao | 2=varias missoes | 3=round-robin")

    args = parser.parse_args()
    roversN = 6
    nave = NaveMae(roversN, args.host, args.port, scenario=args.scenario)
    nave.iniciar()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        nave.parar()
