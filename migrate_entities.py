#!/usr/bin/env python3
"""One-shot migration: services.json + pools.json -> entity.json per service."""
import json
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SERVICES_DIR = os.path.join(DATA_DIR, "services")


def migrate():
    services_path = os.path.join(DATA_DIR, "services.json")
    if not os.path.exists(services_path):
        print("No services.json to migrate")
        return

    with open(services_path) as f:
        entries = json.load(f)

    pools = {}
    pools_path = os.path.join(DATA_DIR, "pools.json")
    if os.path.exists(pools_path):
        with open(pools_path) as f:
            pools = json.load(f)

    for entry in entries:
        name = entry["name"]
        svc_dir = os.path.join(SERVICES_DIR, name.lower())
        os.makedirs(svc_dir, exist_ok=True)

        # Load existing state if any
        state_path = os.path.join(svc_dir, "state.json")
        state = {}
        if os.path.exists(state_path):
            with open(state_path) as f:
                state = json.load(f)

        entry["balance"] = pools.get(name, 0.0)
        entry["state"] = state

        entity_path = os.path.join(svc_dir, "entity.json")
        with open(entity_path, "w") as f:
            json.dump(entry, f, indent=2)

        # Clean up old state.json
        if os.path.exists(state_path):
            os.remove(state_path)

        print(f"  {name}: balance={entry['balance']}, state_keys={list(state.keys())}")

    # Remove old files
    os.rename(services_path, services_path + ".bak")
    if os.path.exists(pools_path):
        os.rename(pools_path, pools_path + ".bak")

    print(f"Migrated {len(entries)} services. Old files renamed to .bak")


if __name__ == "__main__":
    migrate()
