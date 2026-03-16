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


INVOKERS = {
    "claude": {
        "default_model": "sonnet",
        "models": {
            "sonnet": {"alias": "claude-sonnet-4-6"},
            "opus": {"alias": "claude-opus-4-6"},
            "claude-sonnet-4-5": {},
            "claude-sonnet-4-6": {},
            "claude-opus-4-6": {},
        },
    },
    "codex": {
        "default_model": "gpt-5.3-codex",
        "models": {
            "gpt-5.3-codex": {"pricing": (1.75, 14.0)},
            "gpt-5.3-codex-spark": {"pricing": (1.75, 14.0)},
            "gpt-5.4": {"pricing": (2.50, 15.0)},
        },
    },
}

MODEL_ALIASES: dict[str, str] = {}
MODEL_PRICING: dict[str, tuple[float, float]] = {}
DEFAULT_PRICING = (1.75, 14.0)

for _invoker_cfg in INVOKERS.values():
    for _model_name, _model_cfg in _invoker_cfg["models"].items():
        if "alias" in _model_cfg:
            MODEL_ALIASES[_model_name] = _model_cfg["alias"]
        if "pricing" in _model_cfg:
            MODEL_PRICING[_model_name] = _model_cfg["pricing"]


def resolve_model(model: str) -> str:
    return MODEL_ALIASES.get(model, model)


def default_model(invoker: str) -> str:
    return INVOKERS[invoker]["default_model"]


def random_invoker_model() -> tuple[str, str]:
    """Pick a random invoker and its default model (resolved)."""
    import random
    invoker = random.choice(list(INVOKERS.keys()))
    model = resolve_model(INVOKERS[invoker]["default_model"])
    return invoker, model


TOP_MODELS = [("claude", "claude-opus-4-6"), ("codex", "gpt-5.4")]

DEFAULT_CONFIG = SimulationConfig()


def get_agent_name(index: int) -> str:
    if index < len(AGENT_NAMES):
        return AGENT_NAMES[index]
    return f"Agent-{index}"
