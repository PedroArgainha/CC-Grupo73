# mission_scenarios.py
import random

def generate_missions(scenario: int, seed: int = 42):
    rng = random.Random(seed)
    missions = []

    def gen(mid: int):
        return {
            "mission_id": mid,
            "task_type": 0,
            "x": float(rng.randint(-10, 10)),
            "y": float(rng.randint(-10, 10)),
            "radius": float(rng.randint(1, 4)),
            "duracao": float(rng.randint(30, 60)),
        }

    if scenario == 0:
        return []                      # sem missões

    if scenario == 1:
        return [gen(1)]                # 1 missão

    if scenario == 2:
        return [gen(i) for i in range(1, 11)]   # 10 missões

    if scenario == 3:
        return [gen(i) for i in range(1, 7)]    # pool fixo (round-robin)

    raise ValueError("Scenario inválido")
