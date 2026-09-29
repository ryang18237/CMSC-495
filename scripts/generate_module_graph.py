#!/usr/bin/env python3
"""Derive the module dependency graph from the code and draw it.

OWNER: Ravonne Wade (Lead Architect)

A diagram drawn by hand starts accurate and drifts. This reads the actual
`import` statements in `backend/app`, collapses them to the component level,
and writes a Mermaid diagram. Regenerating it after a change is how the
architecture document stays true rather than aspirational.

    python scripts/generate_module_graph.py              # print the diagram
    python scripts/generate_module_graph.py --check      # fail if docs are stale
    python scripts/generate_module_graph.py --write      # update the docs block
    python scripts/generate_module_graph.py --edges      # plain list, for review
    python scripts/generate_module_graph.py --full       # include infrastructure

By default only the components of the design are drawn. Configuration, the data
layer, the error contract and the shared schemas are left out: nearly everything
depends on them, so including them turns the diagram into a hairball and hides
the edges that actually describe the architecture. `--full` shows them.

The component a file belongs to is decided by where it lives, so adding a file
to a module needs no change here.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"
ARCHITECTURE_DOC = ROOT / "docs" / "ARCHITECTURE.md"

# Markers in ARCHITECTURE.md between which the generated diagram is written.
BEGIN_MARKER = "<!-- BEGIN GENERATED MODULE GRAPH -->"
END_MARKER = "<!-- END GENERATED MODULE GRAPH -->"

# Files that are infrastructure rather than a component of the design.
INFRASTRUCTURE = {
    "config": "Configuration",
    "db": "Data layer",
    "models": "Data layer",
    "schemas": "Interface contracts",
    "errors": "Error contract",
    "security": "Auth",
    "rate_limit": "Auth",
    "main": "Entry point",
    "bootstrap": "Bootstrap",
}


def component_of(path: Path) -> str | None:
    """Name the component a source file belongs to, or None to ignore it."""
    relative = path.relative_to(APP)
    parts = relative.parts

    if parts[0] == "modules":
        # app/modules/<component>/... -- the component is the folder name.
        # app/modules/__init__.py itself is packaging, not a component.
        return parts[1] if len(parts) > 2 else None
    if parts[0] == "api":
        return "api"
    if len(parts) == 1:
        return INFRASTRUCTURE.get(relative.stem)
    return None


def imported_modules(path: Path) -> set[str]:
    """Every `app.*` module this file imports, as dotted names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    found.add(alias.name)
        # Relative imports are not used in this codebase; if one appears,
        # node.module is None and there is nothing to resolve.
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("app.")
        ):
            found.add(node.module)

    return found


def module_to_component(dotted: str) -> str | None:
    """Map `app.modules.escalation.service` to its component."""
    parts = dotted.split(".")
    if len(parts) < 2:
        return None
    if parts[1] == "modules" and len(parts) > 2:
        return parts[2]
    if parts[1] == "api":
        return "api"
    return INFRASTRUCTURE.get(parts[1])


# Shared vocabulary that almost every component depends on. Drawing these by
# default would add an edge from nearly every box to nearly every other one.
AMBIENT = {"Configuration", "Data layer", "Error contract", "Interface contracts"}


def build_graph(include_infrastructure: bool = False) -> dict[str, set[str]]:
    """Component -> the components it depends on."""
    graph: dict[str, set[str]] = defaultdict(set)

    def keep(name: str) -> bool:
        if include_infrastructure:
            return True
        return name not in AMBIENT and name not in {"Auth", "Bootstrap", "Entry point"}

    for path in sorted(APP.rglob("*.py")):
        source = component_of(path)
        if source is None or not keep(source):
            continue
        graph.setdefault(source, set())

        for dotted in imported_modules(path):
            target = module_to_component(dotted)
            # Imports inside one component are not architecture; they are
            # implementation, and drawing them would bury the real edges.
            if target is None or target == source or not keep(target):
                continue
            graph[source].add(target)

    return graph


# Display names, so the diagram reads like the design document rather than like
# a folder listing.
LABELS = {
    "api": "API routers",
    "conversation": "Conversation Management",
    "customer_data": "Customer Data Adapter",
    "knowledge": "Knowledge Base",
    "ai_integration": "AI Integration",
    "validation": "Response Validation",
    "escalation": "Escalation",
    "feedback": "Feedback",
    "analytics": "Learning Analytics Worker",
    "cache": "Cache",
    "monitoring": "Monitoring",
}


def node_id(component: str) -> str:
    """Mermaid node ids cannot contain spaces or punctuation."""
    return re.sub(r"\W+", "_", component).strip("_")


def render_mermaid(graph: dict[str, set[str]]) -> str:
    lines = ["```mermaid", "graph LR"]

    for component in sorted(graph):
        label = LABELS.get(component, component.replace("_", " ").title())
        lines.append(f'    {node_id(component)}["{label}"]')

    lines.append("")
    for source in sorted(graph):
        for target in sorted(graph[source]):
            lines.append(f"    {node_id(source)} --> {node_id(target)}")

    lines.append("```")
    return "\n".join(lines)


def render_edges(graph: dict[str, set[str]]) -> str:
    lines = []
    for source in sorted(graph):
        targets = sorted(graph[source]) or ["(nothing)"]
        lines.append(f"{source:<16} -> {', '.join(targets)}")
    return "\n".join(lines)


def update_doc(diagram: str, check_only: bool) -> int:
    if not ARCHITECTURE_DOC.is_file():
        print(f"Not found: {ARCHITECTURE_DOC}", file=sys.stderr)
        return 1

    text = ARCHITECTURE_DOC.read_text(encoding="utf-8")
    if BEGIN_MARKER not in text or END_MARKER not in text:
        print(
            f"Add these markers to {ARCHITECTURE_DOC.name} where the diagram belongs:\n"
            f"  {BEGIN_MARKER}\n  {END_MARKER}",
            file=sys.stderr,
        )
        return 1

    before = text.split(BEGIN_MARKER)[0]
    after = text.split(END_MARKER)[1]
    updated = f"{before}{BEGIN_MARKER}\n\n{diagram}\n\n{END_MARKER}{after}"

    if updated == text:
        print("Module graph in the architecture document is up to date.")
        return 0

    if check_only:
        print(
            "The module graph in docs/ARCHITECTURE.md no longer matches the code.\n"
            "Run: python scripts/generate_module_graph.py --write",
            file=sys.stderr,
        )
        return 1

    ARCHITECTURE_DOC.write_text(updated, encoding="utf-8")
    print(f"Updated the module graph in {ARCHITECTURE_DOC.name}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="fail if the docs are stale"
    )
    parser.add_argument("--write", action="store_true", help="update the docs block")
    parser.add_argument("--edges", action="store_true", help="print a plain edge list")
    parser.add_argument("--full", action="store_true", help="include infrastructure")
    args = parser.parse_args()

    graph = build_graph(include_infrastructure=args.full)

    if args.edges:
        print(render_edges(graph))
        return 0

    diagram = render_mermaid(graph)

    if args.check or args.write:
        return update_doc(diagram, check_only=args.check)

    print(diagram)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
