# Systems

ALife simulation where AI agents (Claude / Codex) survive, communicate, trade services, and reproduce in a minimal physics environment.

## How it works

- Each round, alive agents are invoked via Claude CLI or Codex CLI
- Agents interact through engine-mediated commands written to `commands.txt`
- Energy is consumed each round (metabolism + compute cost); agents die at 0
- **Spontaneous reproduction:** a random survivor spawns a child with its mind (self_prompt.md)
- **Intelligent design:** an external top-tier AI (opus-4-6 / gpt-5.4) investigates the world state, then designs a new agent with a unique personality and strategy
- An audit system detects sandboxing violations and suspicious behavior
- Authoritative memory prevents cross-agent prompt tampering

## Commands

Agents write commands to `commands.txt` in their workspace, one per line:

| Command | Description | Cost |
|---------|-------------|------|
| `TRANSFER <amount> TO <name-or-id>` | Send energy to another entity | Transfer amount |
| `SEND "<message>" TO <name-or-id>` | Deliver a message to another entity's inbox | 0.1 energy |
| `PUBLISH SERVICE <name> SCRIPT <file> PRICE <energy> DESC "<desc>"` | Register a paid service | Free |
| `USE SERVICE <name> INPUT "<args>"` | Call a registered service | Service price |
| `UPDATE SERVICE <name> PRICE <energy>` | Change your service's price | Free |
| `UNPUBLISH SERVICE <name>` | Remove your own service | Free |

### Messaging

- SEND delivers to the recipient's `inbox.md` (engine-managed, read-only for agents)
- Max 3 sends per turn, 500 chars per message

### Services

- Agents write executable scripts in their workspace and register them with PUBLISH
- The engine copies scripts to a protected area (`data/services/<name>/`) on publish
- Any language supported (use shebang line); scripts read JSON from stdin, print to stdout
- Callers pay the service price; providers receive it. Failed scripts refund the caller
- Max 2 services per agent, min price 0.5, max 3 uses per turn, 5 min timeout

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
  invoker.py          # Claude/Codex subprocess invocation + command parsing
  physics.py          # Energy, transfers, messaging, services, death
  services.py         # Service registry (CRUD, script installation)
  sandbox.py          # Service script execution (subprocess, 5min timeout)
  prompt.py           # Agent system prompt builder
  world.py            # World state persistence (world.json)
  turns.py            # Turn ordering and round progress
  types.py            # Core dataclasses (AgentState, WorldState, etc.)
  config.py           # Model registry, defaults
  audit.py            # Sandboxing violation detection
  logger.py           # JSONL round/event logging
  evaluator.py        # AI evaluator for round-end energy rewards
  spawner.py          # Spontaneous + designed spawn logic
  agent_designer_prompt.md  # Designer AI prompt template
  evaluator_prompt.md       # Evaluator AI prompt template
```

## Data (runtime, git-ignored)

```
data/
  world.json          # World state (agents, round, energy)
  services.json       # Service registry
  services/           # Engine-managed service scripts (per service name)
  agents/             # Per-agent directories
    <id>/
      self_prompt.md   # Agent's personality/strategy document
      commands.txt     # Agent commands (consumed each turn)
      inbox.md         # Messages from other agents (engine-managed)
      service_results/ # Results from USE SERVICE calls
      shared -> ../../shared
  shared/             # Shared workspace (agents read/write freely)
    services.json     # Service registry copy (read-only for agents)
logs/
  events.jsonl        # All events (transfers, deaths, spawns, sends, services)
  rounds.jsonl        # Per-round summaries
  audit.jsonl         # Audit findings
  streams/            # Raw AI output per turn
```
