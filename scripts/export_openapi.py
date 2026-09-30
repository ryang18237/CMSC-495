"""Write the API's OpenAPI description to docs/openapi.json.

FastAPI already serves this document live at /openapi.json and renders it at
/docs. Committing a copy does two things the live one cannot: a reviewer can
see a contract change in a pull request diff, and a client team can read the
contract without running the server.

Usage, from the repository root:

    python scripts/export_openapi.py            # rewrite docs/openapi.json
    python scripts/export_openapi.py --check    # exit 1 if the file is stale

CI runs `--check`, so a route or schema change that forgets to regenerate the
file fails the build instead of leaving the committed contract out of date.

The check ignores the two schemas FastAPI generates for its own validation
errors. Their fields change between FastAPI releases, and this API never
returns them -- every validation failure uses our error envelope -- so a
teammate on a slightly different FastAPI version should not fail the check
over a shape no client ever sees.
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
OUTPUT = REPO_ROOT / "docs" / "openapi.json"

FRAMEWORK_SCHEMAS = ("HTTPValidationError", "ValidationError")


def build_document() -> str:
    # Generating the schema touches no database and no provider, but settings
    # are still loaded when the app is created. These defaults keep the export
    # runnable on a clean checkout; real values in the environment win.
    os.environ.setdefault("JWT_SECRET", "openapi-export-only-not-a-real-secret-value")
    os.environ.setdefault("AI_PROVIDER", "builtin")
    os.environ.setdefault("AUTO_BOOTSTRAP", "false")

    sys.path.insert(0, str(BACKEND))
    from app.main import create_app

    document = create_app().openapi()
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def canonical(document_text: str) -> object:
    """The document with framework-owned schemas removed, for comparison."""
    if not document_text:
        return None
    document = json.loads(document_text)
    schemas = document.get("components", {}).get("schemas", {})
    for name in FRAMEWORK_SCHEMAS:
        schemas.pop(name, None)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if docs/openapi.json does not match the running code",
    )
    args = parser.parse_args()

    current = build_document()

    if args.check:
        committed = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if canonical(committed) != canonical(current):
            print(
                "docs/openapi.json is out of date with the code.\n"
                "Run `python scripts/export_openapi.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print("docs/openapi.json is up to date.")
        return 0

    OUTPUT.write_text(current, encoding="utf-8")
    paths = json.loads(current)["paths"]
    operations = sum(len(methods) for methods in paths.values())
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}: {len(paths)} paths, {operations} operations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
