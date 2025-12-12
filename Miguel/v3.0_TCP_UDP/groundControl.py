import json
import argparse
import threading
import asyncio
import websockets

from roverINFO import Rover
from missoes import int_to_mission



def getInput(texto: str, minimo: int, maximo: int) -> int:
    while True:
        try:
            valor = int(input(texto))
            if minimo <= valor <= maximo:
                return valor
            else:
                print(f"Valor fora do intervalo ({minimo} - {maximo}). Tente novamente.")
        except ValueError:
            print("Entrada inválida. Insira um número inteiro.")


class GroundControl:
    def __init__(self, roversN: int, host: str = "127.0.0.1", port: int = 2900):
        self.url = f"ws://{host}:{port}/"
        self.nRovers = roversN

        self.rovers = []
        self.missoes = [0] * roversN           # guarda task_type (para compatibilidade)
        self.estadoRovers = [None] * roversN

        for i in range(roversN):
            self.rovers.append(Rover(id=i + 1))

    # ---------- helpers ----------

    def _safe_task_name(self, task_type: int) -> str:
        """Converte task_type -> nome, mas nunca crasha."""
        try:
            return int_to_mission(task_type)
        except Exception:
            return f"DESCONHECIDA({task_type})"

    def cabecalho(self, tipo: str):
        print(f"=================={tipo}==================\n")

    def rodape(self, tipo: str):
        tam = len(tipo)
        print("=" * (18 + tam + 18))
        print()

    # ---------- UI ----------

    def printMissoes(self):
        texto = "Lista de Missões atuais"
        self.cabecalho(texto)

        for i in range(self.nRovers):
            r = self.rovers[i]
            if self.estadoRovers[i] is None:
                print(f"Rover {i+1}: Sem informação disponível\n")
            else:
                mission_id = getattr(r, "mission_id", 0)
                task_type = r.missao
                print(f"Rover {i+1}")
                print(f"  Mission ID -> {mission_id}")
                print(f"  Task       -> {self._safe_task_name(task_type)} (task_type={task_type})")
                print(f"  Progresso  -> {r.progresso}%\n")

        self.rodape(texto)

    def printRoversAtivos(self):
        texto = "Lista de Rovers Ativos"
        self.cabecalho(texto)

        for i in range(self.nRovers):
            if self.estadoRovers[i] is None:
                continue

            r = self.rovers[i]
            # ativo = tem task_type != 0
            if r.missao != 0:
                mission_id = getattr(r, "mission_id", 0)
                task_type = r.missao

                print(f"Rover {i+1}")
                print(f"  Mission ID -> {mission_id}")
                print(f"  Task       -> {self._safe_task_name(task_type)} (task_type={task_type})")
                print(f"  Progresso  -> {r.progresso}%")
                print("Outra visão do mesmo:\n")
                print(r.to_stringProgresso())
                print()

        self.rodape(texto)

    def printRovers(self):
        texto = "Telemetria mais recente de todos os rovers"
        self.cabecalho(texto)

        for i in range(self.nRovers):
            if self.estadoRovers[i] is None:
                print(f"Rover {i+1}:\nSem informação disponivel\n")
            else:
                print(f"Rover {i+1}:\nTenho informação disponivel")
                print(self.rovers[i].to_string())
                print()

        self.rodape(texto)

    def menu(self):
        menu = "Menu"
        self.cabecalho(menu)
        print("1 -> Ver missões")
        print("2 -> Ver Rovers ativos")
        print("3 -> Ver Estado dos rovers")
        print("4 -> Sair")
        self.rodape(menu)

        opcao = getInput("Introduza a sua opção ->", 1, 4)
        if opcao == 1:
            self.printMissoes()
            return 1
        elif opcao == 2:
            self.printRoversAtivos()
            return 1
        elif opcao == 3:
            self.printRovers()
            return 1
        elif opcao == 4:
            return 0

        return 1

    # ---------- WebSocket callbacks ----------

    def _on_open(self, ws):
        print(f"[GC] Ligado à Nave-Mãe em {self.url}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[GC] Ligação terminada: {close_status_code} {close_msg}")

    def _on_error(self, ws, error):
        print("[GC] Erro WebSocket:", error)

    def _on_message(self, ws, message: str):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            print("[GC] Mensagem inválida:", message)
            return

        tipo = data.get("type")
        if tipo == "rovers_update":
            self._process_rovers_update(data.get("data", []))
        else:
            print("[GC] Mensagem desconhecida:", data)

    # --------- Lógica de atualização ---------

    def _process_rovers_update(self, lista_rovers):
        for rdata in lista_rovers:
            rid = rdata.get("id")
            if rid is None:
                print("[GC] Sem updates para mostrar (sem id)")
                continue

            idx = rid - 1
            if 0 <= idx < self.nRovers:
                self.rovers[idx].update_from_dict(rdata)

                self.estadoRovers[idx] = True
                # mantém compat: isto é task_type
                self.missoes[idx] = self.rovers[idx].missao

    def start_ws(self):
        async def ws_coroutine():
            while True:
                try:
                    async with websockets.connect(self.url) as ws:
                        self._on_open(ws)
                        try:
                            async for message in ws:
                                self._on_message(ws, message)
                        except websockets.ConnectionClosed as e:
                            self._on_close(ws, e.code, e.reason)
                except Exception as e:
                    self._on_error(None, e)
                    await asyncio.sleep(2)

        self.ws_thread = threading.Thread(
            target=lambda: asyncio.run(ws_coroutine()),
            daemon=True,
        )
        self.ws_thread.start()

    def _to_dashboard_rover(self, r: Rover):
        status = (
            "IDLE" if r.state == 0 else
            "WORKING" if r.state == 1 else
            "MOVING" if r.state == 2 else
            "ERROR" if r.state == 3 else
            "OFFLINE"
        )

        mission_id = int(getattr(r, "mission_id", 0))
        task_type = int(r.missao)

        return {
            "id": str(r.id),
            "name": f"ROVER {r.id}",
            "uuid": f"rover-{r.id}",

            "status": status,
            "battery": float(r.bateria),

            # NOVO (recomendado)
            "missionId": mission_id,
            "taskType": task_type,

            # compat (se o frontend esperava "mission", agora manda mission_id)
            "mission": str(mission_id),

            "missionProgress": int(r.progresso),

            "position": {
                "x": float(r.pos_x),
                "y": float(r.pos_y),
                "z": float(r.pos_z),
            },

            "destination": {
                "x": float(r.destino[0]),
                "y": float(r.destino[1]),
                "z": float(r.destino[2]),
            },

            "speed": float(r.velocidade),
            "direction": str(r.direcao),

            "cpu": int(r.proc_use),
            "storage": int(r.storage),
            "sensors": int(r.sensores),
            "frequency": str(r.freq),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", help="Host da Nave-Mãe")
    parser.add_argument("--port", type=int, default=2900, help="Porto WebSocket da Nave-Mãe")
    args = parser.parse_args()

    nrovers = 6
    gc = GroundControl(nrovers, host=args.host, port=args.port)

    gc.start_ws()

    try:
        while gc.menu():
            pass
    except KeyboardInterrupt:
        print("\n[GC] Interrompido pelo utilizador.")
    finally:
        print("[GC] A terminar ligações...")
