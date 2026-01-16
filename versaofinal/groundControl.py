"""
groundControl.py

Interface de Controle Terrestre (Ground Control) para o sistema de rovers.

Visão Geral:
- Fornece uma interface de linha de comando (CLI) para monitorar e controlar rovers remotamente.
- Conecta-se à Nave-Mãe via WebSocket para receber atualizações de telemetria e enviar comandos (ex.: missões manuais).
- Gerencia uma lista de rovers, exibindo missões, estados e permitindo atribuição de missões prioritárias.
- Usa threads para manter a conexão WebSocket em background enquanto o menu CLI roda.

Funcionalidades Principais:
- Menu interativo: Ver missões, rovers ativos, estados e atribuir missões.
- Conexão WebSocket: Recebe updates em tempo real dos rovers via Nave-Mãe.
- Atribuição manual: Permite enviar missões específicas para rovers via WebSocket.

Dependências:
- websockets: Para comunicação WebSocket.
- roverINFO: Para representar rovers.
- missoes: Para mapear IDs de missões para nomes.

Uso:
- Execute como script: python groundControl.py --host <host> --port <port>
- Número de rovers é fixo em 6 (pode ser parametrizado se necessário).
"""

import json
import argparse
import threading
import asyncio
import websockets

from roverINFO import Rover
from missoes import int_to_mission

def getInput(texto: str, minimo: int, maximo: int) -> int:
    """
    Solicita entrada do usuário com validação de intervalo.

    Parâmetros:
        texto (str): Mensagem a exibir para o usuário.
        minimo (int): Valor mínimo aceito.
        maximo (int): Valor máximo aceito.

    Retorna:
        int: Valor inserido pelo usuário dentro do intervalo.

    Comportamento:
        - Repete até obter um inteiro válido no intervalo.
        - Exibe mensagens de erro para entradas inválidas.
    """
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
    """
    Classe principal para o Ground Control.

    Gerencia a conexão WebSocket com a Nave-Mãe, processa updates de rovers e fornece um menu CLI para interação.

    Atributos:
        url (str): URL WebSocket da Nave-Mãe (ex.: ws://host:port/).
        ws: Instância da conexão WebSocket (None se desconectado).
        ws_loop: Loop asyncio para operações WebSocket.
        nRovers (int): Número de rovers gerenciados.
        rovers (list[Rover]): Lista de instâncias Rover.
        missoes (list[int]): Lista de IDs de missões atuais por rover (índice 0-based).
        estadoRovers (list[bool]): Lista indicando se há telemetria recente por rover.
    """

    def __init__(self, roversN: int, host: str = "127.0.0.1", port: int = 2900):
        """
        Inicializa o Ground Control.

        Parâmetros:
            roversN (int): Número de rovers a gerenciar.
            host (str): Host da Nave-Mãe (padrão: 127.0.0.1).
            port (int): Porto WebSocket da Nave-Mãe (padrão: 2900).
        """
        self.url = f"ws://{host}:{port}/"
        self.ws = None
        self.ws_loop = None
        self.nRovers = roversN
        self.rovers = []
        self.missoes = [0] * roversN  # IDs de missões (0 = sem missão)
        self.estadoRovers = [None] * roversN  # True se há telemetria recente
        for i in range(roversN):
            self.rovers.append(Rover(id=i+1))  # IDs 1-based

    def cabecalho(self, tipo: str):
        """Imprime um cabeçalho formatado para seções do menu."""
        print(f"=================={tipo}==================\n")

    def rodape(self, tipo: str):
        """Imprime um rodapé formatado para seções do menu."""
        tam = len(tipo)
        print("=" * (18 + tam + 18))
        print()

    def printMissoes(self):
        """Exibe a lista de missões atuais de todos os rovers."""
        texto = "Lista de Missões atuais"
        self.cabecalho(texto)
        for i in range(self.nRovers):
            print(f"Rover {i+1}\n")
            print(f"Missão Atual -> {int_to_mission(self.missoes[i])}")
        self.rodape(texto)

    def printRoversAtivos(self):
        """Exibe rovers com missões ativas (não 0) e detalhes."""
        texto = "Lista de Rovers Ativos"
        self.cabecalho(texto)
        for i in range(self.nRovers):
            if self.missoes[i] != 0:
                print(f"Rover {i+1}\n")
                print(f"Missão Atual -> {int_to_mission(self.missoes[i])}")
                print("Outra visão do mesmo:\n")
                roverString = self.rovers[i].to_stringProgresso()
                print(roverString)
        self.rodape(texto)

    def menu(self) -> int:
        """
        Exibe o menu principal e processa a escolha do usuário.

        Retorna:
            int: 1 para continuar no loop, 0 para sair.
        """
        menu = "Menu"
        self.cabecalho(menu)

        print("1 -> Ver missões")
        print("2 -> Ver Rovers ativos")
        print("3 -> Ver Estado dos rovers")
        print("4 -> Missão prioridade (atribuir missão manual)")
        print("5 -> Sair")

        self.rodape(menu)

        opcao = getInput("Introduza a sua opção -> ", 1, 5)

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
            self.missao_prioridade()
            return 1
        elif opcao == 5:
            return 0

        self.rodape(menu)
        return 1  # Fallback, embora não deva chegar aqui

    def missao_prioridade(self):
        """
        Permite ao usuário atribuir uma missão manual a um rover via WebSocket.

        Solicita inputs: rover_id, mission_id, x, y, duracao.
        Envia payload JSON para a Nave-Mãe.
        """
        texto = "Missão prioridade"
        self.cabecalho(texto)

        rover_id = getInput("Rover (1..N) -> ", 1, self.nRovers)
        mission_id = getInput("Mission ID (1..6) -> ", 1, 6)
        x = getInput("X (0..15) -> ", 0, 15)
        y = getInput("Y (0..15) -> ", 0, 15)
        duracao = getInput("Duração (seg) (10..600) -> ", 10, 600)

        payload = {
            "type": "assign_mission",
            "rover_id": rover_id,
            "mission_id": mission_id,
            "x": x,
            "y": y,
            "radius": 2.0,  # Fixo
            "duracao": duracao
        }

        ok = self.send_ws(payload)
        if ok:
            print(f"[GC] ✅ Missão prioridade enviada para rover {rover_id}!")
        else:
            print(f"[GC] ❌ Falha ao enviar missão prioridade.")
        
        self.rodape(texto)

    def printRovers(self):
        """Exibe a telemetria mais recente de todos os rovers."""
        texto = "Telemetria mais recente de todos os rovers"
        self.cabecalho(texto)
        for i in range(self.nRovers):
            if self.estadoRovers[i] is None:
                print(f"Rover {i+1}:\nSem informação disponível")
            else:
                print(f"Rover {i+1}:\nTenho informação disponível")
                roverString = self.rovers[i].to_string()
                print(roverString)
        self.rodape(texto)

    def _on_open(self, ws):
        """Callback chamado ao conectar WebSocket."""
        print(f"[GC] Ligado à Nave-Mãe em {self.url}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Callback chamado ao desconectar WebSocket."""
        print(f"[GC] Ligação terminada: {close_status_code} {close_msg}")

    def _on_error(self, ws, error):
        """Callback chamado em erro WebSocket."""
        print(f"[GC] Erro WebSocket:", error)

    def _on_message(self, ws, message: str):
        """
        Processa mensagens recebidas via WebSocket.

        Espera JSON com "type": "rovers_update" e lista de dados de rovers.
        """
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

    def _process_rovers_update(self, lista_rovers):
        """
        Processa update de rovers: atualiza instâncias Rover e estados.

        Parâmetros:
            lista_rovers (list[dict]): Lista de dicionários com dados de rovers.
        """
        for rdata in lista_rovers:
            rid = rdata.get("id")
            if rid is None or not (0 <= rid < self.nRovers):
                continue
            self.rovers[rid].update_from_dict(rdata)
            self.estadoRovers[rid] = True
            self.missoes[rid] = self.rovers[rid].missao

    def start_ws(self):
        """
        Inicia a conexão WebSocket em um thread separado.

        Mantém reconexão automática em caso de falha.
        """
        async def ws_coroutine():
            while True:
                try:
                    async with websockets.connect(self.url) as ws:
                        self.ws = ws
                        self.ws_loop = asyncio.get_running_loop()
                        self._on_open(ws)

                        async for message in ws:
                            self._on_message(ws, message)
                except websockets.ConnectionClosed as e:
                    self._on_close(ws, e.code, e.reason)
                except Exception as e:
                    self._on_error(None, e)
                    self.ws = None
                    self.ws_loop = None
                    await asyncio.sleep(2)  # Reconexão após 2s

        self.ws_thread = threading.Thread(
            target=lambda: asyncio.run(ws_coroutine()),
            daemon=True,
        )
        self.ws_thread.start()

    def send_ws(self, obj: dict) -> bool:
        """
        Envia um objeto JSON via WebSocket para a Nave-Mãe.

        Parâmetros:
            obj (dict): Dados a enviar.

        Retorna:
            bool: True se enviado com sucesso, False caso contrário.
        """
        if not self.ws or not self.ws_loop:
            print("[GC] Não estou ligado à Nave-Mãe (WS).")
            return False

        msg = json.dumps(obj)
        fut = asyncio.run_coroutine_threadsafe(self.ws.send(msg), self.ws_loop)
        try:
            fut.result(timeout=2)
            return True
        except Exception as e:
            print("[GC] Falha ao enviar WS:", e)
            return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ground Control para monitorar e controlar rovers.")
    parser.add_argument("--host", default="127.0.0.1", help="Host da Nave-Mãe")
    parser.add_argument("--port", type=int, default=2900, help="Porto WebSocket da Nave-Mãe")
    args = parser.parse_args()

    nrovers = 6  # Fixo; pode ser argumento se necessário
    gc = GroundControl(nrovers, host=args.host, port=args.port)

    gc.start_ws()

    try:
        while gc.menu():
            pass
    except KeyboardInterrupt:
        print("\n[GC] Interrompido pelo utilizador.")
    finally:
        print("[GC] A terminar ligações...")