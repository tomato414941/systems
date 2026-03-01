# Systems

ALife simulation where AI agents (Claude / Codex) survive, transfer energy, and reproduce in a minimal physics environment.

## How it works

- Each round, alive agents are invoked via Claude CLI or Codex CLI
- Agents can transfer energy to others (`TRANSFER <amount> TO <name>`)
- Energy is consumed each round; agents die at 0
- Spontaneous reproduction: a random survivor spawns a child with its mind (self_prompt.md)
- Authoritative memory prevents cross-agent tampering

## Usage

```bash
# Dry run (no actual AI calls)
python3 -m src --dry-run -a 4 -e 5 -n 2

# Real run with Claude agents
python3 -m src -a 4 -e 8 -n 10 -i claude

# Mixed Claude + Codex
python3 -m src -a 8 -e 8 -n 10
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-a` | Number of agents | 8 |
| `-e` | Initial energy | 8 |
| `-i` | Invoker (`claude` / `codex`) | `claude` |
| `-c` | Concurrency | 4 |
| `-n` | Max rounds | unlimited |
| `--dry-run` | Skip AI calls | false |

## Architecture

```
src/
  __main__.py    # CLI entry point
  orchestrator.py # Round loop, spawn logic
  invoker.py      # Claude/Codex subprocess calls
  physics.py      # Energy, transfers, death
  prompt.py       # Agent prompt builder
  world.py        # World state persistence
  types.py        # Dataclasses
  config.py       # Default settings
  logger.py       # Round/event logging
```
