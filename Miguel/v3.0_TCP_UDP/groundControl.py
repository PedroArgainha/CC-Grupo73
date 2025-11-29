import json
import argparse
from websocket import WebSocketApp

from roverINFO import Rover
from missoes import int_to_mission
import threading


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

    def __init__(self,roversN: int, host: str = "127.0.0.1", port: int = 2900):
        self.url = f"ws://{host}:{port}/"
        i=0
        self.nRovers = roversN
        self.rovers = []
        self.missoes = [0] * roversN
        self.estadoRovers = [None] * roversN
        while i<roversN:
            rover = Rover(id=i)
            self.rovers.append(rover)

            i+=1

    
    def cabecalho (self, tipo:str):
        print (f"=================={tipo}==================\n")

    def rodape (self, tipo:str):
        tam = len(tipo)
        print("=" * (18 + tam + 18))
        print()

    def printMissoes (self):
        i=0
        texto = "Lista de Missões atuais"
        self.cabecalho(texto)
        self.rodape(texto)
        while i<self.nRovers:
            print (f"Rover {i+1}\n")
            print (f"Missão Atual -> {int_to_mission(self.missoes[i])}")
            i+=1
        self.rodape(texto)


    def printRoversAtivos (self):
        i=0
        texto = "Lista de Rovers Ativos"
        self.cabecalho(texto)
        self.rodape(texto)
        while i<self.nRovers:
            if self.missoes[i]!=0:
                print (f"Rover {i+1}\n")
                print (f"Missão Atual -> {int_to_mission(self.missoes[i])}")
                print ("Outra visao do mesmo:\n")
                roverString = self.rovers[i].to_stringProgresso()
                print (roverString)
            i+=1
        self.rodape(texto)

    def menu (self):
        menu = "Menu"
        self.cabecalho(menu)
        print ("1 -> Ver missões")
        print ("2 -> Ver Rovers ativos")
        print ("3 -> Ver Estado dos rovers")
        print ("4 -> Sair")
        self.rodape(menu)
        opcao = getInput("Introduza a sua opção ->",1,4)
        if opcao==1:
            self.printMissoes()
            return 1
        elif opcao==2:
            self.printRoversAtivos()
            return 1
        elif opcao==3:
            self.printRovers()
            return 1
        elif opcao==4:
            return 0
        

        self.rodape(menu)

    def printRovers (self):
        texto = "Telemetria mais recente de todos os rovers"
        self.cabecalho(texto)
        self.rodape(texto)
        i=0
        while i<self.nRovers:
            if self.estadoRovers[i]==None:
                print (f"Rover {i+1}:\nSem informação disponivel")
            else:
                print (f"Rover {i+1}:\n tenho informação disponivel")
                roverString = self.rovers[i].to_string()
                print (roverString)
            i+=1
        self.rodape(texto)

    def _on_open(self, ws):
        print(f"[GC] Ligado à Nave-Mãe em {self.url}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[GC] Ligação terminada: {close_status_code} {close_msg}")

    def _on_error(self, ws, error):
        print(f"[GC] Erro WebSocket:", error)

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
                print("Sem updates para mostar")
                continue
            if 0 <= rid < self.nRovers:
                self.rovers[rid].update_from_dict(rdata)
                self.estadoRovers[rid] = True
                self.missoes[rid] = self.rovers[rid].missao

    def start_ws(self):
        self.ws_app = WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
            on_message=self._on_message,
        )
        self.ws_thread = threading.Thread(target=self.ws_app.run_forever, daemon=True)
        self.ws_thread.start()

    
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
        if gc.ws_app is not None:
            try:
                gc.ws_app.close()
            except Exception:
                pass

