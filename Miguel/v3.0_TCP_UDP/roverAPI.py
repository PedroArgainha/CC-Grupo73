def _cicloML(self):
    

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
