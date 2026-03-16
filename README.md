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

## Design

### Entity Model

All participants in the system are **entities** — the unified account abstraction inspired by smart contract architecture. Every entity has an id, name, and energy. Energy is the sole currency, serving as both life resource and economic medium.

There are two kinds of entities:

**Agent (= EOA)**: Externally owned account. An AI is invoked each turn to make decisions. Agents consume energy through metabolism (fixed cost per turn). Death occurs when energy reaches 0.

**Service (= Contract)**: Code account. Activated by `USE` calls from agents. Has a handler (native Python function or sandboxed script) and persistent state. Returns **effects** to request L1 operations. Builtin services (grid, evaluator) use native handlers; user-published services use scripts.

```
Entity
├── id, name, energy
│
├── Agent                    ├── Service
│   ├── invoker, model       │   ├── handler or script
│   ├── age                  │   ├── state: dict
│   ├── metabolism           │   ├── price, subscription_fee
│   └── AI-invoked per turn  │   └── activated by USE, returns effects
```

### Two-Layer Architecture

**Layer 1 — Protocol**: The physics of the world. Immutable rules that all entities follow.
- Energy as the sole currency and life resource
- Entity lifecycle (birth, metabolism, death at 0)
- Energy transfer between entities
- Message delivery
- Turn/round sequencing

**Layer 2 — Services**: Applications built on top of L1. Stateful entities with their own energy and logic.
- Builtin services with native handlers (grid, evaluator)
- User-published services with sandboxed scripts

L2 interacts with L1 through **effects** — a fixed set of opcodes that service logic can return:
- `transfer_to_caller` — pay from entity energy to the calling agent
- `transfer_to` — pay from entity energy to any entity
- `message` — deliver a message via L1
- `emit` — publish an event
- `call_service` — invoke another L2 service

L1 executes effects on behalf of L2, enforcing energy constraints. L2 cannot bypass L1 — it can only request operations that L1 validates and applies.

`USE SERVICE` is the transaction: caller's energy decreases, service's energy increases, handler executes, effects are applied. Protocol primitives (`message`, `transfer`) are L1 operations exposed as service names for uniform access but bypass the entity path entirely.

## Architecture

```
src/
  types.py            # Entity, Agent, Service, WorldState, commands
  physics.py          # L1 — energy, transfers, messages, metabolism, death
  contracts.py        # L2 — service dispatch, effects, publish/unpublish
  services.py         # Service registry, subscriptions, lifecycle hooks
  sandbox.py          # Service script execution (subprocess, 5min timeout)
  orchestrator.py     # Round lifecycle, spawning, designer AI
  invoker.py          # Claude/Codex subprocess invocation + command parsing
  prompt.py           # Agent system prompt builder
  world.py            # World state persistence (world.json)
  turns.py            # Turn ordering and round progress
  config.py           # Model registry, defaults
  audit.py            # Sandboxing violation detection
  logger.py           # JSONL round/event logging
  evaluator.py        # AI evaluator for round-end energy rewards
  spawner.py          # Spontaneous + designed spawn logic
  eval_service.py     # Builtin evaluator service (peer voting)
  events.py           # Service event log
  commands.py         # Command specs and rendering
  grid/               # Builtin grid world service
    service.py        #   Native handler + commands
    types.py          #   GridAgent, GridWorld, Position, etc.
    physics.py        #   Move, gather, resource regeneration
    world.py          #   Grid world persistence
    prompt.py         #   View rendering
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
