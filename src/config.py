from .types import SimulationConfig

AGENT_NAMES = [
    "Alpha",
    "Beta",
    "Gamma",
    "Delta",
    "Epsilon",
    "Zeta",
    "Eta",
    "Theta",
]

DEFAULT_CONFIG = SimulationConfig()


def get_agent_name(index: int) -> str:
    if index < len(AGENT_NAMES):
        return AGENT_NAMES[index]
    return f"Agent-{index}"
