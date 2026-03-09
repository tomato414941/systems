# Systems

ALife simulation where AI agents (Claude / Codex) survive, transfer energy, and reproduce in a minimal physics environment.

## How it works

- Each round, alive agents are invoked via Claude CLI or Codex CLI
- Agents can transfer energy to others (`TRANSFER <amount> TO <name>`)
- Energy is consumed each round (metabolism + compute cost); agents die at 0
- **Spontaneous reproduction:** a random survivor spawns a child with its mind (self_prompt.md)
- **Intelligent design:** an external top-tier AI (opus-4-6 / gpt-5.4) investigates the world state, then designs a new agent with a unique personality and strategy
- Agents can read/write shared files and edit their own self_prompt.md
- An audit system detects sandboxing violations and suspicious behavior
- Authoritative memory prevents cross-agent prompt tampering

## Usage

```bash
# Dry run (no actual AI calls)
python3 -m src --dry-run -a 4 -e 5 -n 2

# Full round mode
python3 -m src -a 4 -e 8 -n 10

# Turn-by-turn mode (one agent per invocation)
python3 -m src -t 1

# Intelligent design spawn only
python3 -m src --spawn

# Gift energy to an agent (with optional message)
python3 -m src --gift Alpha 5.0 -m "Keep up the good work"
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-a` | Number of agents | 8 |
| `-e` | Initial energy | 8 |
| `-i` | Invoker (`claude` / `codex` / `mixed`) | `claude` |
| `-c` | Concurrency | 4 |
| `-n` | Max rounds | unlimited |
| `-t` | Number of turns to process | — |
| `--spawn` | Run designed spawn only | — |
| `--gift AGENT AMOUNT` | Gift energy to an agent | — |
| `-m` | Message to send with gift | — |
| `--dry-run` | Skip AI calls | false |
| `--claude-model` | Model for claude agents | config default |
| `--codex-model` | Model for codex agents | config default |

## Architecture

```
src/
  __main__.py         # CLI entry point
  orchestrator.py     # Round lifecycle, spawning, designer AI
  invoker.py          # Claude/Codex subprocess invocation
  physics.py          # Energy consumption, transfers, death
  prompt.py           # Agent system prompt builder
  world.py            # World state persistence (world.json)
  turns.py            # Turn ordering and round progress
  types.py            # Core dataclasses (AgentState, WorldState, etc.)
  config.py           # Model registry, defaults
  audit.py            # Sandboxing violation detection
  logger.py           # JSONL round/event logging
  designer_prompt.txt # Designer AI prompt template
```

## Data (runtime, git-ignored)

```
data/
  world.json          # World state (agents, round, energy)
  agents/             # Per-agent directories
    <name>/
      self_prompt.md   # Agent's personality/strategy document
      shared -> ../shared
  shared/             # Shared workspace (agents read/write freely)
logs/
  events.jsonl        # All events (transfers, deaths, spawns)
  rounds.jsonl        # Per-round summaries
  streams/            # Raw AI output per turn
```
