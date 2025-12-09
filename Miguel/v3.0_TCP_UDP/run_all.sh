#!/bin/bash

PROJ="/home/core/CC-Grupo73/Miguel/v3_0_TCP_UDP"

# =======================
#  NAVE-MÃE
# =======================
gnome-terminal --title="NaveMae" -- bash -c "
core-term navemae -- bash -c '
cd $PROJ
python3 navemae.py --host 10.0.0.10 --port 6000
'
"

# =======================
#  ROVER 1
# =======================
gnome-terminal --title="Rover1" -- bash -c "
core-term rover1 -- bash -c '
cd $PROJ
python3 roverAPI.py --id 1 --host 10.0.0.10 --port 6000 --vel 1 --tick 0.5
'
"

# =======================
#  ROVER 2
# =======================
gnome-terminal --title="Rover2" -- bash -c "
core-term rover2 -- bash -c '
cd $PROJ
python3 roverAPI.py --id 2 --host 10.0.0.10 --port 6000 --vel 1 --tick 0.5
'
"

# =======================
#  ROVER 3
# =======================
gnome-terminal --title="Rover3" -- bash -c "
core-term rover3 -- bash -c '
cd $PROJ
python3 roverAPI.py --id 3 --host 10.0.0.10 --port 6000 --vel 1 --tick 0.5
'
"

# =======================
#  GROUND CONTROL
# =======================
gnome-terminal --title="GC" -- bash -c "
core-term gc -- bash -c '
cd $PROJ
python3 groundControl.py --host 10.0.0.10 --port 2900
'
"

echo "====================="
echo "Sistema arrancado!"
echo "====================="
