import socket
import threading
from typing import Optional, Tuple

import ts

import utils as utils
import missionlink as ml
from roverINFO import Rover

from websocket_server import WebsocketServer
import json
import time



class NaveMae:

    def __init__(self,roversN: int, host: str = "0.0.0.0", port: int = 2900):
        i=0
        self.nRovers = roversN
        self.rovers = []
        self.estadoRovers = []
        while i<roversN:
            rover = Rover(id=i)
            self.rovers.append(rover)
            self.estadoRovers[i] = None
            i+=1
    

    def printRovers (self):
        i=0
        while i<self.nRovers:
            if self.estadoRovers[i]==None:
                print (f"Rover {i}:\nSem informação disponivel")
            else:
                self.rovers[i].print()
    
if __name__ == "__main__":
    import argparse
