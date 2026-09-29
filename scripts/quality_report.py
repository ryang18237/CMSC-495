"""Maintainability metrics for the backend, per architectural component.

OWNER: Ravonne Wade (Lead Architect)

Uses radon to measure three things for every Python file under backend/app:

- **Size** -- source lines of code, excluding comments and blank lines.
- **Cyclomatic complexity (CC)** -- the number of independent paths through a
  function. Radon grades it A (1-5) through F (41+). A and B are easy to test
  exhaustively; C and worse deserve a second look.
- **Maintainability index (MI)** -- a 0-100 blend of complexity, size and
  Halstead volume. Radon grades 20+ as A (maintainable).

Results are grouped by the components in the architecture design, so a reader
can see whether complexity is concentrated where the design says the hard work
is (Conversation Management, AI Integration) or leaking into places that should
stay simple (Cache, Monitoring, Escalation rules).

Usage, from the repository root (radon is in backend/requirements-dev.txt):

    python scripts/quality_report.py                 # print the report
    python scripts/quality_report.py --write         # also update docs/metrics/QUALITY.md
    python scripts/quality_report.py --max-cc 15     # exit 1 if any function exceeds 15
"""

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from radon.complexity import cc_rank, cc_visit
from radon.metrics import mi_rank, mi_visit
from radon.raw import analyze

REPO_ROOT = Path(__file__).resolve().parent.parent
APP = REPO_ROOT / "backend" / "app"
OUTPUT = REPO_ROOT / "docs" / "metrics" / "QUALITY.md"

# Friendly names in the order the architecture design lists them.
COMPONENTS = {
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


@dataclass
class Group:
    name: str
    files: int = 0
    sloc: int = 0
    functions: list[tuple[str, int]] = field(default_factory=list)
    mi_scores: list[float] = field(default_factory=list)

    @property
    def mean_cc(self) -> float:
        return sum(cc for _, cc in self.functions) / len(self.functions) if self.functions else 0.0

    @property
    def worst(self) -> tuple[str, int]:
        return max(self.functions, key=lambda item: item[1]) if self.functions else ("-", 0)

    @property
    def mean_mi(self) -> float:
        return sum(self.mi_scores) / len(self.mi_scores) if self.mi_scores else 0.0


def group_for(path: Path) -> str:
    parts = path.relative_to(APP).parts
    if parts[0] == "modules" and len(parts) > 1:
        return COMPONENTS.get(parts[1], parts[1])
    if parts[0] == "api":
        return "API layer"
    return "Shared (config, schemas, errors, security, data)"


def measure() -> tuple[dict[str, Group], list[tuple[int, str]]]:
    groups: dict[str, Group] = {}
    every_function: list[tuple[int, str]] = []

    for path in sorted(APP.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if not source.strip():
            continue
        name = group_for(path)
        group = groups.setdefault(name, Group(name))
        group.files += 1
        group.sloc += analyze(source).sloc
        group.mi_scores.append(mi_visit(source, multi=True))

        for block in cc_visit(source):
            label = f"{path.relative_to(REPO_ROOT).as_posix()}::{block.fullname}"
            group.functions.append((label, block.complexity))
            every_function.append((block.complexity, label))

    every_function.sort(reverse=True)
    return groups, every_function


def render(groups: dict[str, Group], every_function: list[tuple[int, str]]) -> str:
    order = [*COMPONENTS.values(), "API layer", "Shared (config, schemas, errors, security, data)"]
    rows = [groups[name] for name in order if name in groups]

    total_sloc = sum(g.sloc for g in rows)
    total_functions = len(every_function)
    grades: dict[str, int] = defaultdict(int)
    for complexity, _ in every_function:
        grades[cc_rank(complexity)] += 1
    all_mi = [score for g in rows for score in g.mi_scores]
    mi_grades: dict[str, int] = defaultdict(int)
    for score in all_mi:
        mi_grades[mi_rank(score)] += 1

    lines = [
        "| Component | Files | SLOC | Functions | Mean CC | Worst CC | Mean MI |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for g in rows:
        worst_name, worst_cc = g.worst
        lines.append(
            f"| {g.name} | {g.files} | {g.sloc} | {len(g.functions)} | {g.mean_cc:.2f} | "
            f"{worst_cc} ({cc_rank(worst_cc)}) | {g.mean_mi:.1f} |"
        )
    lines.append(
        f"| **Total** | {sum(g.files for g in rows)} | {total_sloc} | {total_functions} | "
        f"{sum(c for c, _ in every_function) / max(1, total_functions):.2f} | "
        f"{every_function[0][0] if every_function else 0} | "
        f"{sum(all_mi) / max(1, len(all_mi)):.1f} |"
    )

    grade_line = " · ".join(
        f"{grade}: {grades.get(grade, 0)}" for grade in ("A", "B", "C", "D", "E", "F")
    )
    mi_line = " · ".join(f"{grade}: {mi_grades.get(grade, 0)}" for grade in ("A", "B", "C"))

    top = "\n".join(
        f"| {complexity} ({cc_rank(complexity)}) | `{label}` |"
        for complexity, label in every_function[:8]
    )

    return (
        "\n".join(lines)
        + "\n\n**Cyclomatic complexity grades, all functions:** "
        + grade_line
        + "\n\n**Maintainability index grades, all files:** "
        + mi_line
        + "\n\n**Most complex functions**\n\n| CC | Function |\n| ---: | --- |\n"
        + top
        + "\n"
    )


MARK_START = "<!-- quality-report:start -->"
MARK_END = "<!-- quality-report:end -->"


def write(report: str) -> None:
    text = OUTPUT.read_text(encoding="utf-8")
    start, end = text.index(MARK_START), text.index(MARK_END)
    OUTPUT.write_text(
        text[: start + len(MARK_START)] + "\n" + report + text[end:], encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backend maintainability metrics.")
    parser.add_argument("--write", action="store_true", help="update docs/metrics/QUALITY.md")
    parser.add_argument("--max-cc", type=int, help="fail if any function exceeds this CC")
    args = parser.parse_args()

    groups, every_function = measure()
    report = render(groups, every_function)
    print(report)

    if args.write:
        write(report)
        print(f"Updated {OUTPUT.relative_to(REPO_ROOT)}")

    if args.max_cc is not None and every_function and every_function[0][0] > args.max_cc:
        worst_cc, worst = every_function[0]
        print(f"{worst} has complexity {worst_cc}, above the limit of {args.max_cc}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
