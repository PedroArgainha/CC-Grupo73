from dataclasses import dataclass, field
from typing import Tuple
import random

from utils import moverPasso, estaNoDestino

from missoes import updateWork,int_to_mission


@dataclass
class Rover:

    id: int
    tick: float = 1.0
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    destino: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    velocidade: float = 0.0
    direcao: float = 0.0
    bateria: float = 100.0
    state: int = 0  # 0=free, 1=working, 2=em movimento, 3=erro
    proc_use: float = 0.0
    storage: float = 0.0
    sensores: int = 0
    freq: int = 0.4  # mensagens por segundo
    dirty: bool = False
    missao:int = 0
    progresso: int = 0
    duracao: int = 60
    working: int = 0

    def updateInfo (self,x,y,z,destino,vel,dir,bat,estado,proc,sto,sens,freq,missao,pro):
        if (self.pos_x != x):
            self.pos_x = x
            self.dirty = True
        if (self.pos_y != y):
            self.pos_y = y
            self.dirty = True
        if (self.pos_z != z):
            self.pos_z = z
            self.dirty = True
        if (self.destino != destino):
            self.destino = destino
            self.dirty = True
        if (self.velocidade != vel):
            self.velocidade = vel
            self.dirty = True
        if (self.direcao != dir):
            self.direcao = dir
            self.dirty = True
        if (self.bateria != bat):
            self.bateria = bat
            self.dirty = True
        if (self.state != estado):
            self.state = estado
            self.dirty = True
        if (self.proc_use != proc):
            self.proc_use = proc
            self.dirty = True
        if (self.storage != sto):
            self.storage =sto
            self.dirty = True
        if (self.sensores != sens):
            self.sensores = sens
            self.dirty = True
        if (self.freq != freq):
            self.freq = freq
            self.dirty = True
        if (self.missao != missao):
            self.missao = missao
            self.dirty = True
        if (self.progresso != pro):
            self.progresso = pro
            self.dirty = True

    def limpaDity (self):
        self.dirty = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pos": [self.pos_x, self.pos_y, self.pos_z],
            "destino": list(self.destino),
            "velocidade": self.velocidade,
            "direcao": self.direcao,
            "bateria": self.bateria,
            "state": self.state,
            "proc_use": self.proc_use,
            "storage": self.storage,
            "sensores": self.sensores,
            "freq": self.freq,
            "miss": self.missao,
            "pro": self.progresso,
        }

    def ajustarEstatisticas(self, mission: str):
        self.proc_use = random.randint(1, 100)
        r = random.randint(1, 100)
        if mission == "movimento":
            r = self.storage + r / 7
        self.storage = r
        if r < 15:
            self.sensores += 1
        if r > 90 and self.sensores > 0:
            self.sensores -= 1

    def moverRover(self):

        novoX, novoY, novoZ, direcao = moverPasso(
            self.pos_x, self.pos_y, self.pos_z, self.destino, self.velocidade, self.tick, self.direcao
        )
        self.pos_x = novoX
        self.pos_y = novoY
        self.pos_z = novoZ
        variacaoVel = random.choice([-1, 0, 1])
        self.velocidade = max(0.0, self.velocidade + variacaoVel)
        self.direcao = direcao
        self.ajustarEstatisticas("movimento")
        self.bateria = max(0.0, self.bateria - 0.5)


    def iterar(self):
        if estaNoDestino(self.pos_x, self.pos_y, self.pos_z, self.destino):
            print("\033[91m Tou no Destino\033[0m")
            self.pos_x, self.pos_y, self.pos_z = self.destino
            if self.progresso==100:
                print("\033[91m Acabei\033[0m")
                self.progresso = 0
                self.missao = 0
                self.state = 0
                self.working = 0
            if self.missao:
                self.state = 1
                self.working = self.working + 1
                ateAgora = self.working/self.duracao * 100
                self.progresso = min(100, int(ateAgora))
                #self.progresso = updateWork (self.missao,self.progresso,self.duracao)
                print("\033[93mTou a trabalhar!\033[0m")
            return
        self.moverRover()
        self.state = 2

    def resetarWork(self):
        self.missao = 0
        self.progresso = 0
        self.state = 0

    def atribiuMission(self,miss):
        self.missao = miss
        self.working = 0

    def traduzEstado(self)->str:
        if self.state == 0:
            return "Livre"
        elif self.state == 1:
            return "A realizar trabalho"
        elif self.state == 2:
            return (f"A ir para o destino atual ({self.destino})")
        else:
            return "Erro"

    def to_string(self) -> str:
        return (
            f"[Rover {self.id}]\n"
            f"  -> Missao atual= {int_to_mission(self.missao)} || Progresso={self.progresso}%\n"
            f"  -> loc=({self.pos_x}, {self.pos_y}, {self.pos_z}) freq={self.freq}/s\n"
            f"  -> bat={self.bateria}% estado={self.traduzEstado()}\n"
            f"  -> proc={self.proc_use} storage={self.storage} "
            f"vel={self.velocidade} dir={self.direcao} sens={self.sensores}"
        )

    def to_stringProgresso(self) -> str:
        return (
            f"  -> Missao atual= {int_to_mission(self.missao)} || Progresso={self.progresso}%\n"
            f"[ -> Atribuida ao Rover {self.id}]\n"
        )

    def from_dict(data: dict) -> "Rover":

        return Rover(
            id = data["id"],
            pos_x = data["pos"][0],
            pos_y = data["pos"][1],
            pos_z = data["pos"][2],
            destino = tuple(data.get("destino", (0,0,0))),
            velocidade = data.get("velocidade", 0.0),
            direcao = data.get("direcao", 0.0),
            bateria = data.get("bateria", 0.0),
            state = data.get("state", 0),
            proc_use = data.get("proc_use", 0.0),
            storage = data.get("storage", 0.0),
            sensores = data.get("sensores", 0),
            freq = data.get("freq", 0.0),
            dirty = False,
            missao = data.get("miss",0),
            progresso=data.get("pro",0),
        )
    
    def update_from_dict(self, data: dict):
        self.pos_x = data["pos"][0]
        self.pos_y = data["pos"][1]
        self.pos_z = data["pos"][2]
        self.destino = tuple(data.get("destino", self.destino))
        self.velocidade = data.get("velocidade", self.velocidade)
        self.direcao = data.get("direcao", self.direcao)
        self.bateria = data.get("bateria", self.bateria)
        self.state = data.get("state", self.state)
        self.proc_use = data.get("proc_use", self.proc_use)
        self.storage = data.get("storage", self.storage)
        self.sensores = data.get("sensores", self.sensores)
        self.freq = data.get("freq", self.freq)
        self.missao = data.get("miss",self.missao)
        self.progresso = data.get("pro",self.progresso)
