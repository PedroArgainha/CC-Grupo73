# mission_scenarios.py
import random

def generate_missions(scenario: int):
    # Removido seed para missões sempre diferentes
    rng = random.Random()
    missions = []

    def gen(mid: int, duracao_min: int = 30, duracao_max: int = 60):
        return {
            "mission_id": mid,
            "task_type": rng.randint(1, 6),
            "x": float(rng.randint(-10, 10)),
            "y": float(rng.randint(-10, 10)),
            "radius": float(rng.randint(1, 4)),
            "duracao": float(rng.randint(duracao_min, duracao_max)),
        }

    if scenario == 0:
        return []                      # sem missões

    if scenario == 1:\
        # Uma missão com duração maior (120-300s)
        return [gen(1, duracao_min=120, duracao_max=300)]

    if scenario == 2:
        # 5 missões que acabam quando atribuídas
        return [gen(i) for i in range(1, 6)]

    if scenario == 3:
        # Pool fixo de 50 missões (round-robin, nunca acaba durante execução)
        return [gen(i) for i in range(1, 51)]

    raise ValueError("Scenario inválido")
