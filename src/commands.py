from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CommandParam:
    name: str
    placeholder: str


@dataclass
class CommandSpec:
    type: str
    params: list[CommandParam]
    limits: str = ""


COMMAND_SPECS: list[CommandSpec] = [
    CommandSpec("transfer", [
        CommandParam("to", "<name-or-id>"),
        CommandParam("amount", "<number>"),
    ]),
    CommandSpec("send_message", [
        CommandParam("to", "<name-or-id>"),
        CommandParam("message", "<text>"),
    ], limits="0.1 energy, max 3/turn, max 500 chars"),
    CommandSpec("publish_service", [
        CommandParam("name", "<name>"),
        CommandParam("script", "<filename>"),
        CommandParam("price", "<number>"),
        CommandParam("description", "<text>"),
    ], limits="min price 0.5, max 2 services"),
    CommandSpec("use_service", [
        CommandParam("name", "<name>"),
        CommandParam("input", "<text>"),
    ], limits="max 3/turn. Results in service_results/"),
    CommandSpec("update_service", [
        CommandParam("name", "<name>"),
        CommandParam("price", "<number>"),
    ]),
    CommandSpec("unpublish_service", [
        CommandParam("name", "<name>"),
    ]),
    CommandSpec("subscribe", [
        CommandParam("name", "<service>"),
    ]),
    CommandSpec("unsubscribe", [
        CommandParam("name", "<service>"),
    ]),
]

COMMAND_TYPES = {spec.type for spec in COMMAND_SPECS}

# Aliases for backward compatibility
TYPE_ALIASES: dict[str, str] = {
    "send": "send_message",
}


def resolve_type(raw: str) -> str:
    return TYPE_ALIASES.get(raw, raw)


def render_commands_reference() -> str:
    lines = []
    for spec in COMMAND_SPECS:
        fields = ', '.join(
            f'"{p.name}": {p.placeholder}' for p in spec.params
        )
        entry = f'{{"type": "{spec.type}", {fields}}}'
        if spec.limits:
            entry += f"  # {spec.limits}"
        lines.append(entry)
    return "\n".join(lines)


def write_commands_file(shared_dir: str) -> None:
    import os
    path = os.path.join(shared_dir, "commands.md")
    content = render_commands_reference()
    with open(path, "w") as f:
        f.write(content)
