import socket
import threading
import time
from typing import Optional, Tuple

from roverINFO import Rover
import ts
import missionlink as ml

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

        self.ml_host = nave_host
        self.ml_port = 50000 # porta UDP 50000 
        self.ml_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ml_sock.settimeout(0.5)      # 500 ms de timeout nas receções
        self.ml_stream_id = rover_id      # usamos o id do rover como stream_id
        self.ml_seq = 1                   # contador de sequência para ML
        self.ml_thread: Optional[threading.Thread] = None

    # ---------- controlo ----------
    def iniciar(self):
        if self.threadEnvio and self.threadEnvio.is_alive():
            return
        self.eventoParar.clear()
        self.threadEnvio = threading.Thread(target=self._cicloEnvio, daemon=True)
        self.threadEnvio.start()

    def parar(self):
        self.eventoParar.set()
        self._fecharLigacao() #fecha Ligacao TCP

        try: 
            self.ml_sock.close()
        except OSError:
            pass

        if self.threadEnvio:
            self.threadEnvio.join(timeout=1)
        if self.ml_thread:
            self.ml_thread.join(timeout=1)


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


    # Arranque de ML separadamente
    rover_api.iniciarMissionLink()

    
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


# controlo MISSION LINK


# método que corre lógica ML num loop
#   manda READY
#   espera MISSION ou NOMISSION
#   e NOMISSION → dorme e tenta outra vez
#   se MISSION → atualiza destino do rover e manda ACK

    # Método de arranque do ML
    # ---------- controlo MissionLink ----------
    def iniciarMissionLink(self):
        """Arranca o thread responsável pelo protocolo MissionLink (UDP)."""
        if self.ml_thread and self.ml_thread.is_alive():
            return
        self.ml_thread = threading.Thread(target=self._cicloMissionLink, daemon=True)
        self.ml_thread.start()

    def _cicloMissionLink(self):
        """Loop principal do Rover no protocolo MissionLink.

        - Envia READY
        - Espera MISSION ou NOMISSION
        - Se NOMISSION: espera 2s e volta a enviar READY
        - Se MISSION: atualiza destino do rover e envia ACK
        (podes mais tarde acrescentar envio de PROGRESS e DONE aqui)
        """
        while not self.eventoParar.is_set():
            # 1) Construir e enviar READY
            msg_ready = ml.build_message(
                msg_type=ml.TYPE_READY,
                seq=self.ml_seq,
                ack=0,
                stream_id=self.ml_stream_id,
                payload=b"",
                flags=ml.FLAG_NEEDS_ACK,
            )
            try:
                self.ml_sock.sendto(msg_ready, (self.ml_host, self.ml_port))
            except OSError as exc:
                print(f"[Rover {self.rover.id}] erro a enviar READY: {exc}")
                time.sleep(1.0)
                continue

            # 2) Esperar resposta (MISSION ou NOMISSION)
            try:
                data, addr = self.ml_sock.recvfrom(4096)
            except socket.timeout:
                # ninguém respondeu → tenta outra vez no próximo ciclo
                # (podias também fazer retransmissão mais esperta aqui)
                print(f"[Rover {self.rover.id}] timeout à espera de MISSION/NOMISSION")
                time.sleep(1.0)
                continue

            try:
                header, payload = ml.parse_message(data)
            except ValueError as exc:
                print(f"[Rover {self.rover.id}] mensagem ML inválida: {exc}")
                continue

            # 3) Tratar resposta
            if header.msg_type == ml.TYPE_NOMISSION:
                print(f"[Rover {self.rover.id}] Nave-Mãe sem missão. Vou esperar e tentar de novo.")
                # ACK opcional da NOMISSION (se assim definires)
                ack_msg = ml.build_message(
                    msg_type=ml.TYPE_ACK,
                    seq=self.ml_seq + 1,
                    ack=header.seq,
                    stream_id=self.ml_stream_id,
                    payload=b"",
                    flags=ml.FLAG_ACK_ONLY,
                )
                try:
                    self.ml_sock.sendto(ack_msg, addr)
                except OSError:
                    pass

                self.ml_seq += 2
                time.sleep(2.0)  # espera 2s antes de voltar a enviar READY
                continue

            if header.msg_type == ml.TYPE_MISSION:
                # Decodificar payload da missão
                miss = ml.parse_payload_mission(payload)
                print(f"[Rover {self.rover.id}] recebi missão:", miss)

                # Atualizar destino do Rover com base na missão
                # (mantemos a coordenada Z atual)
                self.rover.destino = (miss["x"], miss["y"], self.rover.pos_z)

                # Enviar ACK da MISSION
                ack_msg = ml.build_message(
                    msg_type=ml.TYPE_ACK,
                    seq=self.ml_seq + 1,
                    ack=header.seq,
                    stream_id=self.ml_stream_id,
                    payload=b"",
                    flags=ml.FLAG_ACK_ONLY,
                )
                try:
                    self.ml_sock.sendto(ack_msg, addr)
                except OSError:
                    pass

                self.ml_seq += 2

                # - entrar num ciclo de PROGRESS (enviar estado periódicamente)
                # - quando consideramos missão concluída → enviar DONE
                # Por agora, saímos do loop depois de receber uma missão
                # odemos manter o while True e gerir múltiplas missões.
                # para já só while, assumindo 1 missão de cada vez.
                continue

            # Se chegou outro tipo inesperado:
            print(f"[Rover {self.rover.id}] msg_type inesperado no ML: {header.msg_type}")
            time.sleep(1.0)

#socket UDP funcional

        def _cicloML(self):
            """
    LOOP principal do protocolo MissionLink (UDP), no Rover.

    1. Envia READY
    2. Recebe MISSION ou NOMISSION
    3. Se NOMISSION -> espera 2s e repete ciclo
    4. Se MISSION -> atualiza destino, envia ACK
    5. Envia PROGRESS periódico
    6. Quando missão termina -> envia DONE
    """

        print(f"[Rover {self.rover.id}] MissionLink iniciado.")

        while not self.eventoParar.is_set():
            # ----------------------------------------------------
            # 1) Enviar READY
            # ----------------------------------------------------
            msg_ready = ml.build_message(
                msg_type=ml.TYPE_READY,
                seq=self.ml_seq,
                ack=0,
                stream_id=self.ml_stream_id,
                payload=b"",
                flags=ml.FLAG_NEEDS_ACK,
            )

            try:
                self.ml_sock.sendto(msg_ready, (self.ml_host, self.ml_port))
                print(f"[Rover {self.rover.id}] → READY (seq={self.ml_seq})")
            except OSError as e:
                print(f"[Rover {self.rover.id}] erro ao enviar READY:", e)
                time.sleep(1)
                continue

            # ----------------------------------------------------
            # 2) Esperar resposta da Nave-Mãe
            # ----------------------------------------------------
            try:
                data, addr = self.ml_sock.recvfrom(4096)
            except socket.timeout:
                print(f"[Rover {self.rover.id}] timeout à espera de MISSION/NOMISSION")
                time.sleep(1)
                continue

            try:
                header, payload = ml.parse_message(data)
            except ValueError as e:
                print(f"[Rover {self.rover.id}] mensagem ML inválida:", e)
                continue

            # ----------------------------------------------------
            # 3) Se NOMISSION → esperar 2 segundos e voltar ao READY
            # ----------------------------------------------------
            if header.msg_type == ml.TYPE_NOMISSION:
                print(f"[Rover {self.rover.id}] NOMISSION — a aguardar 2s...")

                # ACK da NOMISSION
                ack_msg = ml.build_message(
                    msg_type=ml.TYPE_ACK,
                    seq=self.ml_seq + 1,
                    ack=header.seq,
                    stream_id=self.ml_stream_id,
                    payload=b"",
                    flags=ml.FLAG_ACK_ONLY,
                )
                try:
                    self.ml_sock.sendto(ack_msg, addr)
                except:
                    pass

                self.ml_seq += 2
                time.sleep(2)
                continue

            # ----------------------------------------------------
            # 4) Se for MISSION → descodificar missão
            # ----------------------------------------------------
            if header.msg_type == ml.TYPE_MISSION:
                print(f"[Rover {self.rover.id}] Recebi MISSION (seq={header.seq})")

                mission = ml.parse_payload_mission(payload)

                mission_id = mission["mission_id"]
                x = mission["x"]
                y = mission["y"]
                radius = mission["radius"]

                # Definir destino no Rover (Z mantém-se)
                self.rover.destino = (x, y, self.rover.pos_z)
                self.rover.state = 1  # estado "em missão"

                print(f"[Rover {self.rover.id}] Missão {mission_id} recebida → destino=({x}, {y})")

                # ACK da MISSION
                ack_msg = ml.build_message(
                    msg_type=ml.TYPE_ACK,
                    seq=self.ml_seq + 1,
                    ack=header.seq,
                    stream_id=self.ml_stream_id,
                    payload=b"",
                    flags=ml.FLAG_ACK_ONLY,
                )
                self.ml_sock.sendto(ack_msg, addr)
                print(f"[Rover {self.rover.id}] → ACK MISSION (ack={header.seq})")

                self.ml_seq += 2

                # ----------------------------------------------------
                # 5) Ciclo de PROGRESS enquanto o Rover executa a missão
                # ----------------------------------------------------
                while not self.eventoParar.is_set():
                    # Verificar se já chegou ao destino
                    dx = self.rover.pos_x - x
                    dy = self.rover.pos_y - y
                    dist = (dx*dx + dy*dy) ** 0.5

                    percent = max(0, min(100, int((1 - dist / max(radius, 0.1)) * 100)))

                    # Construir PROGRESS
                    progress_payload = ml.build_payload_progress(
                        mission_id=mission_id,
                        status=0,      # 0 = em curso
                        percent=percent,
                        battery=int(self.rover.bateria),
                        x=self.rover.pos_x,
                        y=self.rover.pos_y,
                    )

                    msg_progress = ml.build_message(
                        msg_type=ml.TYPE_PROGRESS,
                        seq=self.ml_seq,
                        ack=0,
                        stream_id=self.ml_stream_id,
                        payload=progress_payload,
                        flags=ml.FLAG_NEEDS_ACK,
                    )

                    self.ml_sock.sendto(msg_progress, (self.ml_host, self.ml_port))
                    print(f"[Rover {self.rover.id}] → PROGRESS (seq={self.ml_seq}, {percent}%)")

                    # Esperar ACK
                    try:
                        data, addr = self.ml_sock.recvfrom(4096)
                        h_ack, _ = ml.parse_message(data)

                        if h_ack.msg_type == ml.TYPE_ACK and h_ack.ack == self.ml_seq:
                            print(f"[Rover {self.rover.id}] ← ACK PROGRESS ({self.ml_seq})")
                    except socket.timeout:
                        print(f"[Rover {self.rover.id}] timeout PROGRESS → ignorado (TP simplificado).")

                    self.ml_seq += 1

                    # Aguardar 300ms entre PROGRESS
                    time.sleep(0.3)

                    # Se missão concluída → break
                    if dist <= radius:
                        break

                # ----------------------------------------------------
                # 6) Enviar DONE
                # ----------------------------------------------------
                done_payload = ml.build_payload_done(
                    mission_id=mission_id,
                    result_code=0,    # 0 = OK
                )

                msg_done = ml.build_message(
                    msg_type=ml.TYPE_DONE,
                    seq=self.ml_seq,
                    ack=0,
                    stream_id=self.ml_stream_id,
                    payload=done_payload,
                    flags=ml.FLAG_NEEDS_ACK,
                )
                self.ml_sock.sendto(msg_done, (self.ml_host, self.ml_port))
                print(f"[Rover {self.rover.id}] → DONE (seq={self.ml_seq})")

                # Espera ACK ao DONE
                try:
                    data, addr = self.ml_sock.recvfrom(4096)
                    h_ack, _ = ml.parse_message(data)

                    if h_ack.msg_type == ml.TYPE_ACK and h_ack.ack == self.ml_seq:
                        print(f"[Rover {self.rover.id}] ← ACK DONE ({self.ml_seq})")
                except socket.timeout:
                    print(f"[Rover {self.rover.id}] timeout à espera do ACK DONE")

                self.rover.state = 0  # rover volta a idle
                self.ml_seq += 1

                # missão concluída → volta ao READY
                continue

            # ----------------------------------------------------
            # Se chegou um tipo inesperado
            # ----------------------------------------------------
            print(f"[Rover {self.rover.id}] tipo inesperado: {header.msg_type}")

            time.sleep(1)
