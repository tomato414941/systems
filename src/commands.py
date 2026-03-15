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
    ], limits="max 16/turn. Results in service_results/. Builtin services: message, transfer, grid, evaluator."),
    CommandSpec("publish_service", [
        CommandParam("name", "<name>"),
        CommandParam("script", "<filename>"),
        CommandParam("price", "<number>"),
        CommandParam("description", "<text>"),
    ], limits="min price 0.5, max 2 services"),
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
    "send_message": "send_message",
    "transfer": "transfer",
}


def resolve_type(raw: str) -> str:
    return TYPE_ALIASES.get(raw, raw)


DEPRECATION_NOTICE = """
DEPRECATED (removed at R45): "send_message" and "transfer" command types.
Use use_service instead:
  {"type": "use_service", "name": "message", "input": "{\\"to\\": \\"<name>\\", \\"message\\": \\"<text>\\"}"}
  {"type": "use_service", "name": "transfer", "input": "{\\"to\\": \\"<name>\\", \\"amount\\": <number>}"}
""".strip()


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
    lines.append("")
    lines.append(DEPRECATION_NOTICE)
    return "\n".join(lines)


def write_commands_file(managed_dir: str, public_dir: str) -> None:
    import os
    content = render_commands_reference()
    for d in (managed_dir, public_dir):
        path = os.path.join(d, "commands.md")
        with open(path, "w") as f:
            f.write(content)
