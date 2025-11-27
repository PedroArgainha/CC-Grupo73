import json
import argparse
from websocket import WebSocketApp

from roverINFO import Rover
from roverINFO import Rover



class GroundControl:

    def __init__(self,roversN: int, host: str = "127.0.0.1", port: int = 2900):
        self.url = f"ws://{host}:{port}/"
        i=0
        self.nRovers = roversN
        self.rovers = []
        self.estadoRovers = [None] * roversN
        while i<roversN:
            rover = Rover(id=i)
            self.rovers.append(rover)
            i+=1
    

    def printRovers (self):
        i=0
        while i<self.nRovers:
            if self.estadoRovers[i]==None:
                print (f"Rover {i}:\nSem informação disponivel")
            else:
                print (f"Rover {i}:\n tenho informação disponivel")
                self.rovers[i].print()
            i+=1

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
        print ("on message")
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

        self.printRovers()
    
    def run(self):
        ws = WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
            on_message=self._on_message,
        )
        ws.run_forever()
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", help="Host da Nave-Mãe")
    parser.add_argument("--port", type=int, default=2900, help="Porto WebSocket da Nave-Mãe")
    args = parser.parse_args()
    nrovers = 6
    gc = GroundControl(nrovers,host=args.host, port=args.port)
    gc.run()
