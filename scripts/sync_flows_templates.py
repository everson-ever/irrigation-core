#!/usr/bin/env python3
"""Sync Node-RED ui_template node HTML from standalone template files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FLOWS_PATH = PROJECT_DIR / "node-red" / "flows.json"
DEFAULT_TEMPLATES_DIR = PROJECT_DIR / "node-red" / "templates"

TEMPLATE_BY_NODE_ID = {
    "25072c26.808454": "agendamentos.html",
    "dad8cd89.f8f81": "historico.html",
    "681694c2.ce0b1c": "novo-agendamento.html",
    "d6f0b5a1.42c8e3": "configuracoes.html",
}


class SyncError(RuntimeError):
    """Raised when the Node-RED template sync cannot be completed safely."""


def load_flows(flows_path: Path) -> list[dict]:
    try:
        data = json.loads(flows_path.read_text())
    except FileNotFoundError as exc:
        raise SyncError(f"flows.json not found: {flows_path}") from exc
    except json.JSONDecodeError as exc:
        raise SyncError(f"invalid JSON in {flows_path}: {exc}") from exc

    if not isinstance(data, list):
        raise SyncError(f"expected {flows_path} to contain a JSON array")
    return data


def render_flows(flows: list[dict]) -> str:
    return json.dumps(flows, ensure_ascii=False, indent=2) + "\n"


def apply_template_sync(
    flows: list[dict],
    templates_dir: Path,
    template_by_node_id: dict[str, str] | None = None,
) -> None:
    mapping = template_by_node_id or TEMPLATE_BY_NODE_ID
    nodes_by_id = {}
    for node in flows:
        if isinstance(node, dict) and "id" in node:
            nodes_by_id[node["id"]] = node

    missing_nodes = sorted(set(mapping) - set(nodes_by_id))
    if missing_nodes:
        raise SyncError(
            "ui_template node(s) not found in flows.json: " + ", ".join(missing_nodes)
        )

    for node_id, template_name in mapping.items():
        template_path = templates_dir / template_name
        try:
            template = template_path.read_text()
        except FileNotFoundError as exc:
            raise SyncError(f"template file not found: {template_path}") from exc

        node = nodes_by_id[node_id]
        if node.get("type") != "ui_template":
            raise SyncError(
                f"mapped node {node_id} is not a ui_template "
                f"(type={node.get('type')!r})"
            )
        if "format" not in node:
            raise SyncError(f"mapped ui_template node {node_id} has no format field")

        node["format"] = template


def synced_flows_text(flows_path: Path, templates_dir: Path) -> str:
    flows = load_flows(flows_path)
    apply_template_sync(flows, templates_dir)
    return render_flows(flows)


def sync_flows_templates(flows_path: Path, templates_dir: Path, check: bool) -> bool:
    current = flows_path.read_text()
    synced = synced_flows_text(flows_path, templates_dir)

    if current == synced:
        return False

    if check:
        raise SyncError(
            f"{flows_path} is out of sync with templates in {templates_dir}. "
            "Run scripts/sync_flows_templates.py."
        )

    flows_path.write_text(synced)
    return True


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inject node-red/templates/*.html into Node-RED ui_template nodes."
    )
    parser.add_argument(
        "--flows",
        type=Path,
        default=DEFAULT_FLOWS_PATH,
        help=f"path to flows.json (default: {DEFAULT_FLOWS_PATH})",
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=DEFAULT_TEMPLATES_DIR,
        help=f"path to dashboard templates (default: {DEFAULT_TEMPLATES_DIR})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if flows.json would change instead of writing it",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        changed = sync_flows_templates(args.flows, args.templates_dir, args.check)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if changed:
        print(f"Synced {args.flows} from {args.templates_dir}.")
    else:
        print(f"{args.flows} is already in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
