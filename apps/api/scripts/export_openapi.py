"""Export the FastAPI app's OpenAPI spec to a JSON file for FE codegen (packages/api-types).

Usage: uv run python scripts/export_openapi.py
"""

import json
from pathlib import Path

from api.main import app

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "openapi.json"


def main() -> None:
    spec = app.openapi()
    OUTPUT_PATH.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote OpenAPI spec to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
