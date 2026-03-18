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
    CommandSpec("use_service", [
        CommandParam("name", "<name>"),
        CommandParam("input", "<text>"),
    ], limits='max 16/turn. Results in service_results/. Builtin: message, transfer, grid, evaluator. Add "view": true for free read-only query (no effects).'),
    CommandSpec("publish_service", [
        CommandParam("name", "<name>"),
        CommandParam("script", "<filename>"),
        CommandParam("price", "<number>"),
        CommandParam("description", "<text>"),
    ], limits='min price 0.5, max 2 services. Optional: "upgradeable": false for immutable.'),
    CommandSpec("update_service", [
        CommandParam("name", "<name>"),
        CommandParam("price", "<number>"),
    ]),
    CommandSpec("unpublish_service", [
        CommandParam("name", "<name>"),
    ]),
    CommandSpec("deposit", [
        CommandParam("name", "<service>"),
        CommandParam("amount", "<number>"),
    ], limits="owner only"),
    CommandSpec("withdraw", [
        CommandParam("name", "<service>"),
        CommandParam("amount", "<number>"),
    ], limits="owner only"),
    CommandSpec("subscribe", [
        CommandParam("name", "<service>"),
    ]),
    CommandSpec("unsubscribe", [
        CommandParam("name", "<service>"),
    ]),
]

COMMAND_TYPES = {spec.type for spec in COMMAND_SPECS}


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


def write_commands_file(managed_dir: str, public_dir: str) -> None:
    import os
    content = render_commands_reference()
    for d in (managed_dir, public_dir):
        path = os.path.join(d, "commands.md")
        with open(path, "w") as f:
            f.write(content)
