from dataclasses import dataclass, field
from typing import Tuple
import random

from utils import moverPasso, estaNoDestino


@dataclass
class Rover:
    """
    Estado e lógica de movimento de um rover individual.
    Este módulo não gere vários rovers; cada rover corre de forma independente.
    """

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
    freq: int = 1  # mensagens por segundo

    def ajustarEstatisticas(self, mission: str):
        """Ajusta métricas de telemetria de forma pseudo-aleatória."""
        self.proc_use = random.randint(1, 100)
        r = random.randint(1, 100)
        if mission == "movimento":
            r = self.storage + r / 7
        self.storage = r
        if r < 20:
            self.sensores += 1
        if r > 90 and self.sensores > 0:
            self.sensores -= 1

    def moverRover(self):
        """
        Avança uma iteração de movimento e ajusta estatísticas auxiliares.
        """
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
        self.bateria = max(0.0, self.bateria - 0.1)

    def iterar(self):
        if estaNoDestino(self.pos_x, self.pos_y, self.pos_z, self.destino):
            return
        self.moverRover()
