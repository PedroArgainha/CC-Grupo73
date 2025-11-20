from typing import Optional, Dict, Tuple
from utils import mover, estaDestino
import random

# tipos de mensagem no seu protocolo
HELLO = 0
INFO  = 2
END   = 3
FIN   = 4

class Rover:
    def __init__(self,rover_id: int):
        self.id = rover_id
        self.bateria = 100
        self.pos_x = 0
        self.pos_y = 0
        self.pos_z = 0
        self.state = 0  # 0=free, 1=working, 2=em movimento, 3=erro
        self.destino = (0,0,0)

        self.proc_use = 0
        self.storage  = 0
        self.velocidade = 0
        self.direcao = 0
        self.sensores = 0
        self.tick = 1

    def ajustarStats (self,mission):
        r = random.randint (1,100)
        self.proc_use = r
        r = random.randint (1,100)
        if mission == "movimento":
            r = self.storage + r/7
        self.storage = r
        if r < 20:
            self.sensores += 1
        if r>90 and self.sensores>0:
            self.sensores -= 1
        

    def moverRover (self):
        newX, newY, newZ, direcao = mover (self.pos_x,self.pos_y,self.pos_z,self.destino,self.velocidade,self.tick, self.direcao )
        self.pos_x = newX
        self.pos_y = newY
        self.pos_z = newZ
        r = random.choice([-1, 0, 1])
        self.velocidade += r
        self.direcao = direcao
        self.ajustarStats("movimento")



    def iteraRover(self):
        if estaDestino(self.pos_x,self.pos_y,self.pos_z,self.destino):
            #DO mission
            return
        else:
            self.moverRover()


