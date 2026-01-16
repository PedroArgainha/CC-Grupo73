#!/bin/bash

# Caminho para a pasta do teu projeto
PROJ="/home/core/CC-Grupo73/Miguel/v3_0_TCP_UDP"

echo "A iniciar sistema..."

##############################
# NAVE-MÃE
##############################
xterm -T "NaveMae" -e "
core-term navemae -- bash -lc '
cd $PROJ;
python3 navemae.py --host 10.0.0.10 --port 6000;
exec bash'
" &

##############################
# ROVER 1
##############################
xterm -T "Rover1" -e "
core-term rover1 -- bash -lc '
cd $PROJ;
python3 roverAPI.py --id 1 --host 10.0.0.10 --port 6000 --vel 1 --tick 0.5;
exec bash'
" &

##############################
# ROVER 2
##############################
xterm -T "Rover2" -e "
core-term rover2 -- bash -lc '
cd $PROJ;
python3 roverAPI.py --id 2 --host 10.0.0.10 --port 6000 --vel 1 --tick 0.5;
exec bash'
" &

##############################
# ROVER 3
##############################
xterm -T "Rover3" -e "
core-term rover3 -- bash -lc '
cd $PROJ;
python3 roverAPI.py --id 3 --host 10.0.0.10 --port 6000 --vel 1 --tick 0.5;
exec bash'
" &

##############################
# GROUND CONTROL
##############################
xterm -T "GC" -e "
core-term gc -- bash -lc '
cd $PROJ;
python3 groundControl.py --host 10.0.0.10 --port 2900;
exec bash'
" &

echo "=================================="
echo "      Sistema arrancado! "
echo "=================================="
