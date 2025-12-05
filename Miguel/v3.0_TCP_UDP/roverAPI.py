import socket
import threading
import time
from typing import Optional, Tuple

from roverINFO import Rover
import ts
import missionlink as ml


class RoverAPI:

    def __init__(self, rover_id: int, nave_host: str = "127.0.0.1", nave_port: int = 6000, tick: float = 1.0):
        # Estado do rover (usado pela telemetria e pela lógica ML)
        self.rover = Rover(rover_id, tick=tick)

        # Ligação TCP (TelemetryStream) à Nave-Mãe
        self.hostNaveMae = nave_host
        self.portoNaveMae = nave_port
        self.socketLigacao: Optional[socket.socket] = None
        self.streamLigacao = None

        # Controlo de threads
        self.eventoParar = threading.Event()
        self.threadEnvio: Optional[threading.Thread] = None
        self.trancaEnvio = threading.Lock()

        # Ligação UDP (MissionLink) à Nave-Mãe
        self.ml_host = nave_host
        self.ml_port = 50000                       # porta UDP 50000
        self.ml_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ml_sock.settimeout(0.5)               # 500 ms de timeout nas receções
        self.ml_stream_id = rover_id               # usamos o id do rover como stream_id
        self.ml_seq = 1                            # contador de sequência para ML
        self.ml_thread: Optional[threading.Thread] = None

    # ---------- helpers ----------

    def _next_ml_seq(self) -> int:
        """
        Devolve o seq atual e incrementa para a próxima mensagem ML.
        Facilita manter o contador de sequência consistente.
        """
        s = self.ml_seq
        self.ml_seq += 1
        return s

    def atribuir_missao(self, miss: int):
        """Setter simples, caso queiras atribuir missão manualmente (não é o normal em ML)."""
        self.rover.atribiuMission(miss)

    def send_reliable(self, msg_bytes: bytes, seq: int, addr, timeout: float = 0.5, max_retries: int = 5) -> bool:
            """
            Envia msg_bytes para addr de forma fiável:
            - espera um ACK com ack == seq
            - em caso de timeout, reenvia com flag RETX
            - pára ao fim de max_retries tentativas

            Devolve True se recebeu o ACK certo, False se desistiu.
            """
            retries = 0

            # garantir timeout certo neste contexto
            self.ml_sock.settimeout(timeout)

            while retries <= max_retries and not self.eventoParar.is_set():
                try:
                    # envia a mensagem
                    self.ml_sock.sendto(msg_bytes, addr)

                    # espera ACK
                    data, _ = self.ml_sock.recvfrom(4096)
                    try:
                        h_ack, _ = ml.parse_message(data)
                    except ValueError:
                        # lixo → ignora e continua à espera
                        continue

                    if h_ack.msg_type == ml.TYPE_ACK and h_ack.ack == seq:
                        # ACK correto
                        return True

                    # ACK de outra coisa → ignorar neste "canal" e continuar
                    continue

                except socket.timeout:
                    retries += 1
                    print(f"[Rover {self.rover.id}] TIMEOUT seq={seq} → retry {retries}")

                    # marcar RETX na próxima retransmissão
                    try:
                        hdr, payload = ml.parse_message(msg_bytes)
                    except ValueError:
                        # se for mesmo lixo, desistimos
                        break

                    msg_bytes = ml.build_message(
                        msg_type=hdr.msg_type,
                        seq=seq,          # MESMO seq para RETX
                        ack=hdr.ack,
                        stream_id=hdr.stream_id,
                        payload=payload,
                        flags=ml.FLAG_RETX | (hdr.flags & ~ml.FLAG_RETX),
                    )

                except OSError as exc:
                    print(f"[Rover {self.rover.id}] erro em send_reliable: {exc}")
                    break

            print(f"[Rover {self.rover.id}] FALHA: excedeu MAX_RETRIES para seq={seq}")
            return False

    # ---------- controlo geral ----------

    def iniciar(self):
        """Arranca o envio de telemetria (TCP)."""
        if self.threadEnvio and self.threadEnvio.is_alive():
            return
        self.eventoParar.clear()
        self.threadEnvio = threading.Thread(target=self._cicloEnvio, daemon=True)
        self.threadEnvio.start()

    def parar(self):
        """Pede paragem, fecha TCP e UDP e espera (um pouco) pelos threads."""
        self.eventoParar.set()
        self._fecharLigacao()  # fecha ligação TCP

        # Fechar socket UDP do MissionLink
        try:
            self.ml_sock.close()
        except OSError:
            pass

        if self.threadEnvio:
            self.threadEnvio.join(timeout=1)
        if self.ml_thread:
            self.ml_thread.join(timeout=1)

    # ---------- ligação TCP (telemetria) ----------

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
                self.socketLigacao = socket.create_connection(
                    (self.hostNaveMae, self.portoNaveMae),
                    timeout=2.0
                )
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

    # ---------- API básica do rover ----------

    def definirDestino(self, destino: Tuple[float, float, float]):
        self.rover.destino = destino

    def definirVelocidade(self, velocidade: float):
        self.rover.velocidade = max(0.0, velocidade)

    # ---------- ciclo de envio de telemetria (TCP) ----------

    def _cicloEnvio(self):
        """
        Ciclo que:
          - avança a simulação do rover (rover.iterar())
          - envia frames TS (HELLO + INFO) via TCP para a Nave-Mãe
        """
        freq_hz = int(1 / self.rover.tick) if self.rover.tick > 0 else 0

        # Envia HELLO no arranque
        self._enviarDados(ts.codificarFrame(ts.TYPE_HELLO, self.rover, freq_hz))

        while not self.eventoParar.is_set():
            self.rover.iterar()
            self._enviarDados(ts.codificarFrame(ts.TYPE_INFO, self.rover, freq_hz))
            time.sleep(self.rover.tick)

    # ---------- MissionLink (UDP) ----------

    def iniciarMissionLink(self):
        """Arranca o thread responsável pelo protocolo MissionLink (UDP)."""
        if self.ml_thread and self.ml_thread.is_alive():
            return
        self.ml_thread = threading.Thread(target=self._cicloMissionLink, daemon=True)
        self.ml_thread.start()

    def _cicloMissionLink(self):
                """
                Loop principal do protocolo MissionLink (UDP):

                    READY -> (MISSION | NOMISSION)
                    MISSION -> ciclo PROGRESS -> DONE

                A posição, bateria e progresso são atualizados pelo _cicloEnvio()
                através de rover.iterar() + lógica em roverINFO.
                """
                print(f"[Rover {self.rover.id}] MissionLink iniciado.")

                while not self.eventoParar.is_set():
                    # ============================================================
                    # 1) Enviar READY a pedir missão
                    #    (Aqui NÃO usamos send_reliable, porque o ACK vem piggyback
                    #     na própria resposta MISSION/NOMISSION.)
                    # ============================================================
                    seq_ready = self._next_ml_seq()
                    msg_ready = ml.build_message(
                        msg_type=ml.TYPE_READY,
                        seq=seq_ready,
                        ack=0,
                        stream_id=self.ml_stream_id,
                        payload=b"",
                        flags=ml.FLAG_NEEDS_ACK,
                    )

                    try:
                        self.ml_sock.sendto(msg_ready, (self.ml_host, self.ml_port))
                        print(f"[Rover {self.rover.id}] → READY (seq={seq_ready})")
                    except OSError as exc:
                        print(f"[Rover {self.rover.id}] erro a enviar READY: {exc}")
                        time.sleep(1.0)
                        continue

                    # ============================================================
                    # 2) Esperar resposta (MISSION ou NOMISSION)
                    # ============================================================
                    try:
                        data, addr = self.ml_sock.recvfrom(4096)
                    except socket.timeout:
                        # ninguém respondeu → tenta outra vez no próximo ciclo
                        print(f"[Rover {self.rover.id}] timeout à espera de MISSION/NOMISSION")
                        time.sleep(1.0)
                        continue
                    except OSError:
                        # socket foi fechado em parar()
                        break

                    try:
                        header, payload = ml.parse_message(data)
                    except ValueError as exc:
                        print(f"[Rover {self.rover.id}] mensagem ML inválida: {exc}")
                        continue

                    # ============================================================
                    # 3) Tratar NOMISSION
                    # ============================================================
                    if header.msg_type == ml.TYPE_NOMISSION:
                        print(f"[Rover {self.rover.id}] Nave-Mãe sem missão. Vou esperar e tentar de novo.")

                        # ACK da NOMISSION (ACK_ONLY)
                        seq_ack = self._next_ml_seq()
                        ack_msg = ml.build_message(
                            msg_type=ml.TYPE_ACK,
                            seq=seq_ack,
                            ack=header.seq,
                            stream_id=self.ml_stream_id,
                            payload=b"",
                            flags=ml.FLAG_ACK_ONLY,
                        )
                        try:
                            self.ml_sock.sendto(ack_msg, addr)
                        except OSError:
                            pass

                        time.sleep(2.0)  # espera 2s antes de voltar a enviar READY
                        continue

                    # ============================================================
                    # 4) Tratar MISSION
                    # ============================================================
                    if header.msg_type == ml.TYPE_MISSION:
                        try:
                            miss = ml.parse_payload_mission(payload)
                        except ValueError as exc:
                            print(f"[Rover {self.rover.id}] MISSION inválida: {exc}")
                            continue

                        print(f"[Rover {self.rover.id}] recebi missão: {miss}")

                        mission_id = miss["mission_id"]
                        x = miss["x"]
                        y = miss["y"]
                        radius = miss["radius"]
                        duracao = miss["duracao"]   # ML já tem este campo

                        # Atualizar destino do Rover com base na missão (Z mantém-se)
                        self.rover.destino = (x, y, self.rover.pos_z)

                        # Atualizar info de missão no Rover
                        self.rover.atribiuMission(mission_id)  # missão em formato int
                        self.rover.duracao = duracao           # usado pelo updateWork
                        self.rover.progresso = 0               # começa a 0%
                        self.rover.state = 1                   # "a realizar trabalho"

                        # ACK da MISSION
                        seq_ack = self._next_ml_seq()
                        ack_msg = ml.build_message(
                            msg_type=ml.TYPE_ACK,
                            seq=seq_ack,
                            ack=header.seq,
                            stream_id=self.ml_stream_id,
                            payload=b"",
                            flags=ml.FLAG_ACK_ONLY,
                        )
                        try:
                            self.ml_sock.sendto(ack_msg, addr)
                            print(f"[Rover {self.rover.id}] → ACK MISSION (ack={header.seq})")
                        except OSError:
                            pass

                        # ========================================================
                        # 5) Ciclo de PROGRESS enquanto a missão decorre
                        #    NOTA: quem atualiza pos/progresso é o _cicloEnvio()
                        #    via rover.iterar() + updateWork() em roverINFO.
                        # ========================================================
                        while not self.eventoParar.is_set():
                            # Se por algum motivo a missão mudou externamente, saímos
                            if self.rover.missao != mission_id:
                                print(f"[Rover {self.rover.id}] missão mudou durante PROGRESS, a sair do ciclo.")
                                break

                            # percentagem baseada no progresso lógico interno (0–100)
                            percent = max(0, min(100, int(self.rover.progresso)))

                            dx = self.rover.pos_x - x
                            dy = self.rover.pos_y - y
                            dist = (dx * dx + dy * dy) ** 0.5

                            # Construir PROGRESS com o estado atual
                            progress_payload = ml.build_payload_progress(
                                mission_id=mission_id,
                                status=0,                # 0 = em curso
                                percent=percent,
                                battery=int(self.rover.bateria),
                                x=self.rover.pos_x,
                                y=self.rover.pos_y,
                            )

                            seq_prog = self._next_ml_seq()
                            msg_progress = ml.build_message(
                                msg_type=ml.TYPE_PROGRESS,
                                seq=seq_prog,
                                ack=0,
                                stream_id=self.ml_stream_id,
                                payload=progress_payload,
                                flags=ml.FLAG_NEEDS_ACK,
                            )

                            try:
                                ok = self.send_reliable(
                                    msg_progress,
                                    seq_prog,
                                    (self.ml_host, self.ml_port),
                                )
                                if not ok:
                                    print(f"[Rover {self.rover.id}] falha a enviar PROGRESS fiável (seq={seq_prog})")
                                    break
                                print(f"[Rover {self.rover.id}] → PROGRESS (seq={seq_prog}, {percent}%)")
                            except OSError as exc:
                                print(f"[Rover {self.rover.id}] erro ao enviar PROGRESS: {exc}")
                                break

                            # Pausa entre envios de PROGRESS
                            time.sleep(0.3)

                            # Condição de fim de missão:
                            #   - chegou suficientemente perto do destino
                            #   - OU o progresso já atingiu 100%
                            if dist <= radius or percent >= 100:
                                print(
                                    f"[Rover {self.rover.id}] missão {mission_id} concluída "
                                    f"(dist={dist:.2f}, prog={percent}%)."
                                )
                                break

                        # ========================================================
                        # 6) Enviar DONE
                        # ========================================================
                        done_payload = ml.build_payload_done(
                            mission_id=mission_id,
                            result_code=0,    # 0 = OK
                        )

                        seq_done = self._next_ml_seq()
                        msg_done = ml.build_message(
                            msg_type=ml.TYPE_DONE,
                            seq=seq_done,
                            ack=0,
                            stream_id=self.ml_stream_id,
                            payload=done_payload,
                            flags=ml.FLAG_NEEDS_ACK,
                        )
                        try:
                            ok = self.send_reliable(
                                msg_done,
                                seq_done,
                                (self.ml_host, self.ml_port),
                            )
                            if not ok:
                                print(f"[Rover {self.rover.id}] falha a enviar DONE fiável (seq={seq_done})")
                            else:
                                print(f"[Rover {self.rover.id}] → DONE (seq={seq_done})")
                        except OSError as exc:
                            print(f"[Rover {self.rover.id}] erro ao enviar DONE: {exc}")

                        # Limpar estado de missão no rover
                        self.rover.state = 0          # rover volta a idle
                        self.rover.resetarWork()      # limpar missao + progresso

                        # missão concluída → volta ao READY (próxima iteração do while)
                        continue

                    # ============================================================
                    # 7) Se chegou outro tipo inesperado
                    # ============================================================
                    print(f"[Rover {self.rover.id}] msg_type inesperado no ML: {header.msg_type}")
                    time.sleep(1.0)


# ---------- modo standalone ----------

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

    # Envio de telemetria TCP
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
