"""Architecture, component boundaries and data flow -- enforced.

OWNER: Ravonne Wade (Lead Architect)

The design document says who may depend on whom. Prose cannot stop anyone
adding an import, so these tests read the actual `import` statements in
`backend/app` and fail when a boundary in the design is crossed.

They deliberately parse source rather than importing the application: the point
is to catch a bad dependency before it is ever executed, and parsing also means
the rules apply to code that is never reached at runtime.

When one of these fails, the question to ask is which is wrong -- the code or
the design. Both answers are legitimate. Changing a rule here is a deliberate
architecture decision and should come with an ADR in `docs/adr/`, not a quiet
edit.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
MODULES = APP / "modules"


# ---------------------------------------------------------------------------
# Reading the graph
# ---------------------------------------------------------------------------
def _source_files() -> list[Path]:
    return sorted(path for path in APP.rglob("*.py") if path.name != "__init__.py")


def _imports(path: Path) -> set[str]:
    """Every `app.*` module a file imports, as dotted names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("app."))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("app."):
                found.add(node.module)

    return found


def _component(path: Path) -> str | None:
    """The component a file belongs to: a folder under app/modules, or None."""
    relative = path.relative_to(APP)
    if relative.parts[0] == "modules" and len(relative.parts) > 2:
        return relative.parts[1]
    return None


def _component_of_import(dotted: str) -> str | None:
    parts = dotted.split(".")
    if len(parts) > 2 and parts[1] == "modules":
        return parts[2]
    return None


def _component_dependencies() -> dict[str, set[str]]:
    """Component -> the other components it imports from."""
    graph: dict[str, set[str]] = defaultdict(set)

    for path in _source_files():
        source = _component(path)
        if source is None:
            continue
        graph.setdefault(source, set())
        for dotted in _imports(path):
            target = _component_of_import(dotted)
            if target is not None and target != source:
                graph[source].add(target)

    return graph


def _offenders(predicate) -> list[str]:
    """Files whose imports break a rule, reported as 'path: import'."""
    problems: list[str] = []
    for path in _source_files():
        for dotted in sorted(_imports(path)):
            if predicate(path, dotted):
                problems.append(f"{path.relative_to(APP.parent)}: imports {dotted}")
    return problems


# ---------------------------------------------------------------------------
# The core modular monolith must not depend on its own HTTP layer
# ---------------------------------------------------------------------------
def test_no_module_imports_the_api_layer() -> None:
    """Modules are called by the routers, never the other way round.

    If a module reached into `app.api`, the business logic could no longer be
    used by the analytics worker or a future background job without dragging
    FastAPI along with it.
    """
    problems = _offenders(
        lambda path, dotted: _component(path) is not None and dotted.startswith("app.api")
    )
    assert not problems, "A module imported the API layer:\n  " + "\n  ".join(problems)


# ---------------------------------------------------------------------------
# The Customer Data Adapter owns the legacy schema
# ---------------------------------------------------------------------------
LEGACY_MODEL = "LegacyMemberMaster"

# Two permitted exceptions, for reasons that are not boundary violations:
#   models.py   declares the table -- every model lives there so one metadata
#               object creates the whole schema
#   bootstrap.py inserts the synthetic rows the demo needs
# The rule is about who *reads* the legacy shape, not where it is defined.
_LEGACY_ALLOWED = {"modules/customer_data", "models.py", "bootstrap.py"}


def test_only_the_adapter_touches_the_legacy_personnel_table() -> None:
    """The whole point of the adapter is that the legacy shape stops there.

    Every other module consumes `CustomerContext`. If a second reader appeared,
    a change to the personnel system would become a change in two places, and
    the field-minimisation rules could be bypassed entirely.
    """
    problems: list[str] = []

    for path in _source_files():
        relative = str(path.relative_to(APP))
        if any(relative.startswith(allowed) for allowed in _LEGACY_ALLOWED):
            continue
        if LEGACY_MODEL in path.read_text(encoding="utf-8"):
            problems.append(str(path.relative_to(APP.parent)))

    assert not problems, (
        f"{LEGACY_MODEL} is referenced outside the Customer Data Adapter:\n  "
        + "\n  ".join(problems)
    )


# ---------------------------------------------------------------------------
# The AI Integration Module is the only place a provider exists
# ---------------------------------------------------------------------------
def test_no_provider_is_imported_outside_the_ai_module() -> None:
    """Swapping the model provider must stay a configuration change.

    Callers depend on `AIIntegrationService`; only the AI module knows a
    provider exists. Tests are exempt because they legitimately construct fake
    providers to drive failure paths.
    """
    problems = _offenders(
        lambda path, dotted: (
            "ai_integration.providers" in dotted and _component(path) != "ai_integration"
        )
    )
    assert not problems, "A provider was imported outside the AI module:\n  " + "\n  ".join(
        problems
    )


def test_the_ai_module_never_touches_the_database() -> None:
    """AI Integration takes a context and returns a result -- nothing more.

    Keeping it free of the data layer is what makes it the component that could
    be extracted into its own service first, and what makes it testable without
    a database.
    """
    problems = _offenders(
        lambda path, dotted: (
            _component(path) == "ai_integration" and dotted in {"app.db", "app.models"}
        )
    )
    assert not problems, "The AI module reached into the data layer:\n  " + "\n  ".join(problems)


# ---------------------------------------------------------------------------
# Escalation owns escalation, and nothing else
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("forbidden", ["ai_integration", "customer_data", "knowledge"])
def test_escalation_does_not_reach_into_other_components(forbidden: str) -> None:
    """From the design rationale: the Escalation Module owns escalation rules,
    case creation, queue status and transfer context. It does not query the
    personnel database and it does not build prompts."""
    dependencies = _component_dependencies().get("escalation", set())
    assert forbidden not in dependencies, (
        f"Escalation now depends on {forbidden}. "
        "That responsibility belongs to the Conversation Management Module."
    )


# ---------------------------------------------------------------------------
# One orchestrator
# ---------------------------------------------------------------------------
def test_only_the_api_layer_drives_conversation_management() -> None:
    """Conversation Management is the orchestrator; nothing orchestrates it.

    If another module imported it, there would be two places that decide the
    order of a customer turn, and they would eventually disagree.
    """
    problems = _offenders(
        lambda path, dotted: (
            "modules.conversation" in dotted
            and _component(path) is not None
            and _component(path) != "conversation"
        )
    )
    assert not problems, "A module imported Conversation Management:\n  " + "\n  ".join(problems)


# ---------------------------------------------------------------------------
# Leaf infrastructure stays leaf
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("leaf", ["cache", "monitoring"])
def test_supporting_components_depend_on_no_other_component(leaf: str) -> None:
    """Cache and Monitoring are used by other components and use none.

    A dependency in the other direction would make them impossible to call from
    anywhere without dragging half the application in, and would risk a cycle.
    """
    dependencies = _component_dependencies().get(leaf, set())
    assert not dependencies, (
        f"{leaf} now depends on {sorted(dependencies)}. Supporting components must stay leaves."
    )


# ---------------------------------------------------------------------------
# No cycles
# ---------------------------------------------------------------------------
def test_component_dependencies_form_no_cycles() -> None:
    """A cycle between components means the boundary between them is fiction.

    It also makes them impossible to extract, test or reason about separately,
    which is the entire justification for the modular monolith.
    """
    graph = _component_dependencies()
    visiting: set[str] = set()
    done: set[str] = set()
    cycle: list[str] = []

    def walk(node: str, trail: list[str]) -> bool:
        if node in visiting:
            cycle.extend(trail[trail.index(node) :] + [node])
            return True
        if node in done:
            return False

        visiting.add(node)
        for neighbour in sorted(graph.get(node, set())):
            if walk(neighbour, trail + [node]):
                return True
        visiting.discard(node)
        done.add(node)
        return False

    for component in sorted(graph):
        if walk(component, []):
            break

    assert not cycle, "Dependency cycle between components: " + " -> ".join(cycle)


# ---------------------------------------------------------------------------
# Shared vocabulary stays shared
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("shared", ["schemas.py", "errors.py", "config.py"])
def test_shared_contracts_depend_on_no_component(shared: str) -> None:
    """Contracts, errors and configuration are the vocabulary every component
    speaks. If one of them imported a component, every component would
    transitively depend on that one."""
    path = APP / shared
    offending = sorted(
        dotted for dotted in _imports(path) if _component_of_import(dotted) is not None
    )
    assert not offending, f"{shared} imports a component: {offending}"


# ---------------------------------------------------------------------------
# The map matches the territory
# ---------------------------------------------------------------------------
DOCUMENTED_COMPONENTS = {
    "conversation",
    "customer_data",
    "knowledge",
    "ai_integration",
    "validation",
    "escalation",
    "feedback",
    "analytics",
    "cache",
    "monitoring",
}


def test_every_component_on_disk_is_one_the_design_names() -> None:
    """A new folder under app/modules is a new box on the architecture diagram.

    Failing here is the reminder to update `docs/ARCHITECTURE.md` and the
    component diagram rather than letting the code quietly grow a component
    nobody drew.
    """
    on_disk = {
        path.name for path in MODULES.iterdir() if path.is_dir() and path.name != "__pycache__"
    }
    assert on_disk == DOCUMENTED_COMPONENTS, (
        "The components on disk no longer match the design.\n"
        f"  only on disk: {sorted(on_disk - DOCUMENTED_COMPONENTS)}\n"
        f"  only in the design: {sorted(DOCUMENTED_COMPONENTS - on_disk)}"
    )


def test_every_component_has_a_service_entry_point() -> None:
    """Each component exposes its behaviour through a named module.

    Without this, a component can become a loose bag of functions that other
    components import from arbitrarily, and the boundary stops meaning anything.
    """
    expected_entry_points = {
        "conversation": "service.py",
        "customer_data": "adapter.py",
        "knowledge": "service.py",
        "ai_integration": "service.py",
        "validation": "service.py",
        "escalation": "service.py",
        "feedback": "service.py",
        "analytics": "worker.py",
        "cache": "service.py",
        "monitoring": "service.py",
    }

    missing = [
        f"{component}/{filename}"
        for component, filename in expected_entry_points.items()
        if not (MODULES / component / filename).is_file()
    ]
    assert not missing, "Component entry points are missing:\n  " + "\n  ".join(missing)
