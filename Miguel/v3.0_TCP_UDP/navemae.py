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
import argparse
import random

contador = 0



class NaveMae:

    def __init__(self,roversN: int, host: str = "0.0.0.0", port: int = 6000):
        self.host = host
        self.port = port

        # ---------- lista tarefas ----------
        self.tarefas = []
        self.scenario = 3          # número de cenários
        self.task_counter = 0      # contador p/ cenário 3 (infinito)
        self.manual_missions = {}  # rover_id -> list[tuple(mission_id, task_id, x, y, radius, duracao)]
        self.manual_task_counter = 1000  # só para task_id não colidir com os automáticos

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
        self.ml_last_seq = {}
        # MISSION pendente por rover: enquanto não houver ACK da MISSION, reenvia-se a mesma
        # stream_id -> {"mission_seq": int, "reply_bytes": bytes, "missao": tuple|None}
        self.ml_pending_mission = {}

        i=0
        self.nRovers = roversN
        self.rovers = []
        while i<roversN:
            rover = Rover(id=i)
            self.rovers.append(rover)
            i+=1

        # ================== MissionLink helpers ==================

    def _prox_seq_ml(self) -> int:
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
        try:
            data = json.loads(message)
        except Exception:
            print("[NaveMae] WS: JSON inválido:", message)
            return

        if data.get("type") != "assign_mission":
            print("[NaveMae] WS: tipo desconhecido:", data.get("type"))
            return

        try:
            rover_id = int(data["rover_id"])
            mission_id = int(data["mission_id"])
            x = int(data["x"])
            y = int(data["y"])
            radius = float(data.get("radius", 2.0))
            duracao = int(data.get("duracao", 60))
        except Exception as e:
            print("[NaveMae] WS: payload inválido:", e, data)
            return

        # task_id único para poderes ver "incrementos"
        self.manual_task_counter += 1
        task_id = self.manual_task_counter

        missao = (mission_id, task_id, x, y, radius, duracao)
        self.manual_missions.setdefault(rover_id, []).append(missao)

        print(f"[NaveMae] WS: missão manual enfileirada para rover {rover_id}: {missao}")

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
            print("[NaveMae] Nenhum rover dirty, nada para enviar")
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
        finally:
            print("Enviei JSON")


    def criaTarefa(self, task_id: int):
        """
        Devolve uma missão no formato:
        (mission_id, task_id, x, y, radius, duracao)
        """
        mission_id = random.randint(1, 6)
        x = random.randint(0, 15)
        y = random.randint(0, 15)
        radius = 2.0

        if random.randint(1, 3) == 1:
            duracao = random.randint(30, 60)
        else:
            duracao = random.randint(45, 60)

        return (mission_id, task_id, x, y, radius, duracao)

    # ================== MissionLink handlers ==================
    def _ml_is_duplicate(self, stream_id: int, header: ml.MLHeader) -> bool:
        last = self.ml_last_seq.get(stream_id)

        if last is None:
            self.ml_last_seq[stream_id] = header.seq
            return False

        if header.seq > last:
            self.ml_last_seq[stream_id] = header.seq
            return False

        if header.seq == last:
            return True

        return True

    def _ml_handle_ready(self, stream_id: int, header: ml.MLHeader, addr):
        print(f"[NaveMae/ML] READY de rover {stream_id} (seq={header.seq})")

        # ============================================================
        # 0) IDEMPOTÊNCIA: se já há resposta pendente (MISSION/NOMISSION)
        #    ainda não confirmada por ACK, reenvia a MESMA resposta.
        # ============================================================
        pending = self.ml_pending_mission.get(stream_id)
        if pending is not None:
            try:
                self.ml_sock.sendto(pending["reply_bytes"], addr)
                print(
                    f"[NaveMae/ML] Rover {stream_id} tem resposta pendente "
                    f"(mission_seq={pending['mission_seq']}) → reenviei a mesma"
                )
            except OSError:
                pass
            return

        # ============================================================
        # 1) ESCOLHER MISSÃO: PRIORIDADE para manuais do GC
        # ============================================================
        missao = None
        
        # 1.1) Verifica se há missões manuais para este rover
        fila_manual = self.manual_missions.get(stream_id)
        if fila_manual:
            missao = fila_manual[0]  # peek (não remove ainda)
            print(f"[NaveMae/ML] Rover {stream_id}: usando missão MANUAL da fila")
        
        # 1.2) Se não há manual, usa missões automáticas do cenário
        if missao is None:
            if self.scenario in (1, 2, 4):
                missao = self.tarefas[0] if self.tarefas else None
            elif self.scenario == 3:
                missao = self.criaTarefa(self.task_counter + 1)
            
            if missao:
                print(f"[NaveMae/ML] Rover {stream_id}: usando missão AUTOMÁTICA (scenario {self.scenario})")

        # ============================================================
        # 2) Se não há missão disponível → NOMISSION
        # ============================================================
        if missao is None:
            reply_seq = self._prox_seq_ml()
            msg = ml.build_message(
                msg_type=ml.TYPE_NOMISSION,
                seq=reply_seq,
                ack=header.seq,
                stream_id=stream_id,
                payload=b"",
                flags=ml.FLAG_NEEDS_ACK,
            )
            try:
                self.ml_sock.sendto(msg, addr)
            except OSError:
                pass

            self.ml_pending_mission[stream_id] = {
                "mission_seq": None,
                "reply_bytes": msg,
                "missao": None,
            }

            print(f"[NaveMae/ML] → NOMISSION para rover {stream_id}")
            return

        # ============================================================
        # 3) Temos missão → construir payload e enviar MISSION
        # ============================================================
        mission_id, task_number, x, y, radius, duracao = missao
        print(f"[NaveMae/ML] missão escolhida: idM={mission_id} TaskN={task_number} x={x} y={y} r={radius} d={duracao}")

        payload = ml.build_payload_mission(mission_id, task_number, x, y, radius, duracao)

        # Guardar estado interno
        self.ml_estado[stream_id] = {
            "mission_id": mission_id,
            "task_number": task_number,
            "target": (x, y),
            "radius": radius,
            "duracao": duracao,
            "ultimo_progress": None,
            "done": False,
        }

        # Atualizar o rover "espelho" local (GC)
        try:
            self.rovers[stream_id - 1].atribiuMission(mission_id)
        except Exception:
            pass

        # Enviar MISSION
        mission_seq = self._prox_seq_ml()
        msg = ml.build_message(
            msg_type=ml.TYPE_MISSION,
            seq=mission_seq,
            ack=header.seq,
            stream_id=stream_id,
            payload=payload,
            flags=ml.FLAG_NEEDS_ACK,
        )

        try:
            self.ml_sock.sendto(msg, addr)
        except OSError:
            pass

        # Guardar como pending até ACK
        self.ml_pending_mission[stream_id] = {
            "mission_seq": mission_seq,
            "reply_bytes": msg,
            "missao": missao,
        }

        print(f"[NaveMae/ML] → MISSION task={task_number} missao={mission_id} para rover {stream_id} (seq={mission_seq})")


    def _ml_handle_progress(self, stream_id: int, header: ml.MLHeader, payload: bytes, addr):
        try:
            info = ml.parse_payload_progress(payload)
        except ValueError as exc:
            print(f"[NaveMae/ML] PROGRESS inválido de rover {stream_id}: {exc}")
            return

        mission_id = info["mission_id"]

        estado = self.ml_estado.get(stream_id)
        taskn = estado.get("task_number") if estado else None

        if not estado or estado.get("mission_id") != mission_id:
            print(
                f"[NaveMae/ML] PROGRESS fora de contexto de rover {stream_id}: "
                f"missao={mission_id}"
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

        if self._ml_is_duplicate(stream_id, header):
            print(
                f"[NaveMae/ML] PROGRESS duplicado de rover {stream_id} "
                f"(seq={header.seq})"
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

        self.ml_estado.setdefault(stream_id, {})
        self.ml_estado[stream_id]["ultimo_progress"] = info

        print(
            f"[NaveMae/ML] PROGRESS rover {stream_id}: "
            f"task={taskn} missao={info['mission_id']} status={info['status']} "
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
        taskn = estado.get("task_number") if estado else None

        if not estado or estado.get("mission_id") != mission_id:
            print(
                f"[NaveMae/ML] DONE rover {stream_id}: "
                f"task={taskn} missao={mission_id} resultado={result_code}"
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

        if self._ml_is_duplicate(stream_id, header) or estado.get("done"):
            print(
                f"[NaveMae/ML] DONE duplicado de rover {stream_id} "
                f"para missao={mission_id}"
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

        estado["done"] = True
        self.ml_estado[stream_id] = estado

        print(
            f"[NaveMae/ML] DONE rover {stream_id}: "
            f"missao={mission_id} resultado={result_code}"
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


    def iniciar(self):
        self.gerar_tarefas(self.scenario)
        
        self.servidorSocket.bind((self.host, self.port))
        self.servidorSocket.listen()
        print(f"[NaveMae] a escutar em {self.host}:{self.port}")
        threading.Thread(target=self._cicloAceitacao, daemon=True).start()
        
        self.ml_sock.bind((self.host, self.ml_port))
        print(f"[NaveMae] a escutar ML (UDP) em {self.host}:{self.ml_port}")
        self.ml_thread = threading.Thread(target=self._cicloML, daemon=True)
        self.ml_thread.start()

        self.start_ws_server(host=self.host, port=2900)


    def parar(self):
        self.terminar = True

        try:
            self.servidorSocket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.servidorSocket.close()

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
            mensagem = (
                f"[NaveMae] Rover {hdr.id_rover}:\n"
                f"  -> loc=({hdr.pos_x},{hdr.pos_y},{hdr.pos_z}) freq={hdr.freq}/s\n"
                f"  -> bat={hdr.bateria}% estado={hdr.state}\n"
                f"  -> proc={pl.proc_use} storage={pl.storage} vel={pl.velocidade} dir={pl.direcao} sens={pl.sensores}"
            )
            realIndex = hdr.id_rover - 1
            self.rovers[realIndex].updateInfo(hdr.pos_x,hdr.pos_y,hdr.pos_z,(pl.x,pl.y,pl.z),pl.velocidade,pl.direcao,hdr.bateria,hdr.state,pl.proc_use,pl.storage,pl.sensores,hdr.freq,self.rovers[realIndex].missao,pl.progresso)
            print (f"Recebi Rover {hdr.id_rover}\n")
            return
        if tipo in (ts.TYPE_END, ts.TYPE_FIN, 3):
            print(f"[NaveMae] Rover {hdr.id_rover} desligou-se da nave ({origem})")
            return
        print(ts.frameParaTexto(frame, origem=origem))
    
    
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

                pending = self.ml_pending_mission.get(sid)
                if pending is None:
                    continue

                # Se ACK confirma a MISSION pendente
                if pending["mission_seq"] is not None and header.ack == pending["mission_seq"]:
                    self.ml_pending_mission.pop(sid, None)

                    # Se era missão manual, consumir da fila
                    fila_manual = self.manual_missions.get(sid)
                    if fila_manual and pending["missao"] == fila_manual[0]:
                        fila_manual.pop(0)
                        if not fila_manual:
                            self.manual_missions.pop(sid, None)
                        print(f"[NaveMae/ML] ✅ Missão manual consumida da fila do rover {sid}")

                    # Avançar cenário
                    if self.scenario in (2, 4):
                        if self.tarefas and pending["missao"] == self.tarefas[0]:
                            self.tarefas.pop(0)
                    elif self.scenario == 3:
                        self.task_counter += 1

                elif pending["mission_seq"] is None:
                    self.ml_pending_mission.pop(sid, None)
            else:
                print(f"[NaveMae/ML] tipo de mensagem desconhecido: {msg_type} de rover {sid}")


    def gerar_tarefas(self, scenario: int):
        self.tarefas = []

        if scenario == 1:
            return

        elif scenario == 2:
            self.tarefas.append(self.criaTarefa(1))
            self.tarefas.append(self.criaTarefa(2))
            return

        elif scenario == 3:
            return

        elif scenario == 4:
            self.tarefas = [
                (1, 1, 2, 2, 2.0, 30),
                (2, 2, 8, 3, 2.0, 35),
                (3, 3, 12, 10, 2.0, 40),
                (4, 4, 5, 12, 2.0, 45),
            ]
            return

        else:
            raise ValueError("Scenario inválido")

    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nave Mãe minimal para frames TS.")
    parser.add_argument("--host", default="0.0.0.0", help="endereço de escuta")
    parser.add_argument("--port", type=int, default=6000, help="port TCP para aceitar rovers")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4], default = 3, help="cenário de missões (1-4)")
    args = parser.parse_args()
    roversN = 3
    nave = NaveMae(roversN,args.host, args.port)

    nave.scenario = args.scenario
    nave.gerar_tarefas(nave.scenario)

    nave.iniciar()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        nave.parar()