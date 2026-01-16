"""
navemae.py

Módulo da Nave-Mãe (NaveMae) para o sistema de rovers.

Visão Geral:
- A Nave-Mãe é o componente central que coordena rovers, gerencia missões e fornece interfaces para monitoramento.
- Funcionalidades principais:
  - Recebe telemetria TCP dos rovers (usando protocolo TS).
  - Gerencia missões via MissionLink (UDP): atribui missões, processa progresso e conclusão.
  - Oferece interface WebSocket para Ground Control (GC): recebe comandos manuais e envia updates de rovers.
  - Suporta cenários de missões (1-4): finitos ou infinitos, com geração automática ou manual.
- Threads: Usa múltiplas threads para telemetria, MissionLink e WebSocket, garantindo operação concorrente.
- Cenários:
  - 1: Uma missão finita.
  - 2: Duas missões finitas.
  - 3: Missões infinitas (geradas sob demanda).
  - 4: Missões fixas pré-definidas.

Dependências:
- ts: Para parsing de frames de telemetria.
- missionlink: Para protocolo MissionLink.
- roverINFO: Para representar rovers.
- websocket_server: Para servidor WebSocket.
- utils: Funções auxiliares (não usado diretamente aqui).

Uso:
- Execute como script: python navemae.py --host <host> --port <port> --scenario <1-4>
- Número de rovers é fixo em 3 (pode ser parametrizado).
"""

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

contador = 0  # Contador global (aparentemente não usado; pode ser removido)

class NaveMae:
    """
    Classe principal da Nave-Mãe.

    Coordena telemetria, missões e comunicação com Ground Control.

    Atributos:
        host (str): Host para escuta (TCP, UDP, WS).
        port (int): Porto TCP para telemetria.
        tarefas (list): Lista de missões automáticas (para cenários finitos).
        scenario (int): Cenário atual (1-4).
        task_counter (int): Contador para missões infinitas (cenário 3).
        manual_missions (dict): Missões manuais por rover (rover_id -> list[tuple]).
        manual_task_counter (int): Contador para IDs únicos de missões manuais.
        servidorSocket: Socket TCP para telemetria.
        terminar (bool): Flag para parar threads.
        ml_port (int): Porto UDP para MissionLink.
        ml_sock: Socket UDP para MissionLink.
        ml_thread: Thread para loop MissionLink.
        ml_seq (int): Sequência global para MissionLink.
        ws_server: Servidor WebSocket para GC.
        ws_client: Cliente WebSocket conectado (único).
        ml_estado (dict): Estado de missões por stream_id.
        ml_last_seq (dict): Última sequência por stream_id (para detectar duplicatas).
        ml_pending_mission (dict): Missões pendentes de ACK por stream_id.
        nRovers (int): Número de rovers.
        rovers (list[Rover]): Lista de instâncias Rover.
    """

    def __init__(self, roversN: int, host: str = "0.0.0.0", port: int = 6000):
        """
        Inicializa a Nave-Mãe.

        Parâmetros:
            roversN (int): Número de rovers a gerenciar.
            host (str): Host para escuta.
            port (int): Porto TCP para telemetria.
        """
        self.host = host
        self.port = port

        # ---------- Lista de tarefas ----------
        self.tarefas = []  # Missões automáticas
        self.scenario = 3  # Cenário padrão
        self.task_counter = 0  # Para cenário infinito
        self.manual_missions = {}  # rover_id -> list[tuple(mission_id, task_id, x, y, radius, duracao)]
        self.manual_task_counter = 1000  # IDs únicos para manuais

        # ---------- Telemetria (TCP) ----------
        self.servidorSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.servidorSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.terminar = False

        # ---------- Mission Link (UDP) ----------
        self.ml_port = 50000  # Porto UDP para ML
        self.ml_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ml_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ml_thread: Optional[threading.Thread] = None
        self.ml_seq = 1  # Sequência global

        # ---------- Ground Control WebSockets (GC) ----------
        self.ws_server: WebsocketServer | None = None
        self.ws_client = None  # Um único cliente

        # Estado do rover por stream_id
        self.ml_estado = {}
        self.ml_last_seq = {}
        # MISSION pendente por rover: enquanto não houver ACK, reenvia
        self.ml_pending_mission = {}  # stream_id -> {"mission_seq": int, "reply_bytes": bytes, "missao": tuple|None}

        self.nRovers = roversN
        self.rovers = [Rover(id=i) for i in range(roversN)]  # IDs 0-based

    # ================== MissionLink helpers ==================

    def _prox_seq_ml(self) -> int:
        """Retorna a sequência atual e incrementa para a próxima."""
        s = self.ml_seq
        self.ml_seq += 1
        return s

    # ================== WEBSOCKET (GROUND CONTROL) ==================

    def start_ws_server(self, host: str = "0.0.0.0", port: int = 2900):
        """
        Inicia o servidor WebSocket para Ground Control.

        Parâmetros:
            host (str): Host do servidor.
            port (int): Porto do servidor.
        """
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
        """Callback para novo cliente WebSocket."""
        print("[NaveMae] Ground Control ligado:", client)
        self.ws_client = client  # Só um cliente

    def _ws_cliente_saiu(self, client, server):
        """Callback para cliente WebSocket desconectado."""
        print("[NaveMae] Ground Control desligou-se:", client)
        if self.ws_client == client:
            self.ws_client = None

    def _ws_msg_recebida(self, client, server, message: str):
        """
        Processa mensagens recebidas via WebSocket (ex.: missões manuais).

        Espera JSON com "type": "assign_mission".
        """
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

        # task_id único
        self.manual_task_counter += 1
        task_id = self.manual_task_counter

        missao = (mission_id, task_id, x, y, radius, duracao)
        self.manual_missions.setdefault(rover_id, []).append(missao)

        print(f"[NaveMae] WS: missão manual enfileirada para rover {rover_id}: {missao}")

    def _ws_loop_envio(self):
        """Loop para enviar updates de rovers via WebSocket."""
        while not self.terminar:
            self._enviar_dirty_rovers()
            time.sleep(1)

    def _enviar_dirty_rovers(self):
        """Envia dados de rovers 'dirty' (modificados) para GC."""
        if not self.ws_server or not self.ws_client:
            return
        ficheiro = [r.to_dict() for r in self.rovers if r.dirty]
        if not ficheiro:
            print("[NaveMae] Nenhum rover dirty, nada para enviar")
            return

        # Limpa flag dirty
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
        Cria uma missão aleatória.

        Retorna:
            tuple: (mission_id, task_id, x, y, radius, duracao)
        """
        mission_id = random.randint(1, 6)
        x = random.randint(0, 15)
        y = random.randint(0, 15)
        radius = 2.0
        duracao = random.randint(30, 60) if random.randint(1, 3) == 1 else random.randint(45, 60)
        return (mission_id, task_id, x, y, radius, duracao)

    # ================== MissionLink handlers ==================

    def _ml_is_duplicate(self, stream_id: int, header: ml.MLHeader) -> bool:
        """
        Verifica se a mensagem é duplicada baseada na sequência.

        Retorna True se duplicada.
        """
        last = self.ml_last_seq.get(stream_id)
        if last is None:
            self.ml_last_seq[stream_id] = header.seq
            return False
        if header.seq > last:
            self.ml_last_seq[stream_id] = header.seq
            return False
        return header.seq == last

    def _ml_handle_ready(self, stream_id: int, header: ml.MLHeader, addr):
        """
        Processa mensagem READY: atribui missão ao rover.

        Prioriza missões manuais, depois automáticas.
        """
        print(f"[NaveMae/ML] READY de rover {stream_id} (seq={header.seq})")

        # Idempotência: reenvia resposta pendente se houver
        pending = self.ml_pending_mission.get(stream_id)
        if pending is not None:
            try:
                self.ml_sock.sendto(pending["reply_bytes"], addr)
                print(f"[NaveMae/ML] Rover {stream_id} tem resposta pendente → reenviei")
            except OSError:
                pass
            return

        # Escolher missão: prioridade para manuais
        missao = None
        fila_manual = self.manual_missions.get(stream_id)
        if fila_manual:
            missao = fila_manual[0]  # Peek
            print(f"[NaveMae/ML] Rover {stream_id}: usando missão MANUAL")
        if missao is None:
            if self.scenario in (1, 2, 4):
                missao = self.tarefas[0] if self.tarefas else None
            elif self.scenario == 3:
                missao = self.criaTarefa(self.task_counter + 1)
            if missao:
                print(f"[NaveMae/ML] Rover {stream_id}: usando missão AUTOMÁTICA (scenario {self.scenario})")

        # Se não há missão → NOMISSION
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

        # Enviar MISSION
        mission_id, task_number, x, y, radius, duracao = missao
        print(f"[NaveMae/ML] missão escolhida: idM={mission_id} TaskN={task_number} x={x} y={y} r={radius} d={duracao}")

        payload = ml.build_payload_mission(mission_id, task_number, x, y, radius, duracao)
        self.ml_estado[stream_id] = {
            "mission_id": mission_id,
            "task_number": task_number,
            "target": (x, y),
            "radius": radius,
            "duracao": duracao,
            "ultimo_progress": None,
            "done": False,
        }
        try:
            self.rovers[stream_id - 1].atribiuMission(mission_id)
        except Exception:
            pass

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
        self.ml_pending_mission[stream_id] = {
            "mission_seq": mission_seq,
            "reply_bytes": msg,
            "missao": missao,
        }
        print(f"[NaveMae/ML] → MISSION task={task_number} missao={mission_id} para rover {stream_id} (seq={mission_seq})")

    def _ml_handle_progress(self, stream_id: int, header: ml.MLHeader, payload: bytes, addr):
        """Processa mensagem PROGRESS: atualiza estado e envia ACK."""
        try:
            info = ml.parse_payload_progress(payload)
        except ValueError as exc:
            print(f"[NaveMae/ML] PROGRESS inválido de rover {stream_id}: {exc}")
            return

        mission_id = info["mission_id"]
        estado = self.ml_estado.get(stream_id)
        if not estado or estado.get("mission_id") != mission_id:
            print(f"[NaveMae/ML] PROGRESS fora de contexto de rover {stream_id}")
            # Envia ACK mesmo assim
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
            print(f"[NaveMae/ML] PROGRESS duplicado de rover {stream_id}")
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

        self.ml_estado[stream_id]["ultimo_progress"] = info
        print(f"[NaveMae/ML] PROGRESS rover {stream_id}: {info['percent']}% bat={info['battery']}")

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
        """Processa mensagem DONE: marca missão como concluída e envia ACK."""
        try:
            info = ml.parse_payload_done(payload)
        except ValueError as exc:
            print(f"[NaveMae/ML] DONE inválido de rover {stream_id}: {exc}")
            return

        mission_id = info["mission_id"]
        result_code = info["result_code"]
        estado = self.ml_estado.get(stream_id)
        if not estado or estado.get("mission_id") != mission_id:
            print(f"[NaveMae/ML] DONE fora de contexto de rover {stream_id}")
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
            print(f"[NaveMae/ML] DONE duplicado de rover {stream_id}")
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

    def iniciar(self):
        """Inicia todos os serviços: telemetria, MissionLink e WebSocket."""
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
        """Para todos os serviços e fecha conexões."""
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
        """Loop para aceitar conexões TCP de rovers."""
        while not self.terminar:
            try:
                conn, addr = self.servidorSocket.accept()
            except OSError:
                break
            threading.Thread(target=self._cicloCliente, args=(conn, addr), daemon=True).start()
            print(f"[NaveMae] ligação de {addr}")

    def _cicloCliente(self, conn: socket.socket, addr: Tuple[str, int]):
        """Loop para processar frames de um cliente TCP."""
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
        """Recebe exatamente n bytes do socket."""
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
        """Processa e imprime dados de um frame TS, atualizando rovers."""
        hdr, pl = frame.header, frame.payload
        origem = f"{addr[0]}:{addr[1]}"
        tipo = hdr.tipo
        if tipo in (ts.TYPE_HELLO, 1):
            print(f"[NaveMae] Rover {hdr.id_rover} ligou-se à nave ({origem})")
            return
        if tipo == ts.TYPE_INFO:
            print(f"[NaveMae] Recebi Rover {hdr.id_rover}")
            realIndex = hdr.id_rover - 1
            self.rovers[realIndex].updateInfo(
                hdr.pos_x, hdr.pos_y, hdr.pos_z, (pl.x, pl.y, pl.z),
                pl.velocidade, pl.direcao, hdr.bateria, hdr.state,
                pl.proc_use, pl.storage, pl.sensores, hdr.freq,
                self.rovers[realIndex].missao, pl.progresso
            )
            return
        if tipo in (ts.TYPE_END, ts.TYPE_FIN, 3):
            print(f"[NaveMae] Rover {hdr.id_rover} desligou-se da nave ({origem})")
            return
        print(ts.frameParaTexto(frame, origem=origem))

    def _cicloML(self):
        """Loop principal para processar mensagens MissionLink via UDP."""
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
                if pending["mission_seq"] is not None and header.ack == pending["mission_seq"]:
                    self.ml_pending_mission.pop(sid, None)
                    # Consome missão manual se aplicável
                    fila_manual = self.manual_missions.get(sid)
                    if fila_manual and pending["missao"] == fila_manual[0]:
                        fila_manual.pop(0)
                        if not fila_manual:
                            self.manual_missions.pop(sid, None)
                        print(f"[NaveMae/ML] ✅ Missão manual consumida da fila do rover {sid}")
                    # Avança cenário
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
        """
        Gera tarefas baseadas no cenário.

        Parâmetros:
            scenario (int): Cenário (1-4).
        """
        self.tarefas = []
        if scenario == 1:
            return
        elif scenario == 2:
            self.tarefas.append(self.criaTarefa(1))
            self.tarefas.append(self.criaTarefa(2))
            return
        elif scenario == 3:
            return  # Infinito
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
    parser = argparse.ArgumentParser(description="Nave Mãe para sistema de rovers.")
    parser.add_argument("--host", default="0.0.0.0", help="endereço de escuta")
    parser.add_argument("--port", type=int, default=6000, help="port TCP para telemetria")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4], default=3, help="cenário de missões (1-4)")
    args = parser.parse_args()
    roversN = 3
    nave = NaveMae(roversN, args.host, args.port)

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