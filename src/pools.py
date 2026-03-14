import json
import os

POOLS_FILE = "pools.json"


def _pools_path(data_dir: str) -> str:
    return os.path.join(data_dir, POOLS_FILE)


def load_pools(data_dir: str) -> dict[str, float]:
    path = _pools_path(data_dir)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_pools(pools: dict[str, float], data_dir: str) -> None:
    path = _pools_path(data_dir)
    with open(path, "w") as f:
        json.dump(pools, f, indent=2)


def add_to_pool(name: str, amount: float, data_dir: str) -> None:
    pools = load_pools(data_dir)
    pools[name] = pools.get(name, 0.0) + amount
    save_pools(pools, data_dir)


def get_pool(name: str, data_dir: str) -> float:
    pools = load_pools(data_dir)
    return pools.get(name, 0.0)
