"""Answer "if this model/source breaks, what's downstream" from dbt's own manifest.

dbt already computes the full dependency graph on every compile/build
(`dbt/target/manifest.json`); this script just walks it. No separate lineage
tool, no re-parsing SQL — the DAG dbt itself builds and trusts is the same
one this script reports from, so it can never drift out of sync with what
dbt actually does.

Usage:
    uv run python scripts/impact_analysis.py fct_orders
    uv run python scripts/impact_analysis.py raw.orders   # a source table

Requires dbt/target/manifest.json to exist — run `dbt compile` or
`dbt build` first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "dbt" / "target" / "manifest.json"


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        print(
            f"No manifest at {MANIFEST_PATH}. Run `dbt compile` or `dbt build` "
            "from the dbt/ directory first."
        )
        sys.exit(1)
    return json.loads(MANIFEST_PATH.read_text())


def find_node_id(manifest: dict[str, Any], name: str) -> str:
    """Resolve a bare model name or 'schema.table' source name to its unique_id."""
    for unique_id, node in manifest["nodes"].items():
        if node["resource_type"] == "model" and node["name"] == name:
            return unique_id

    if "." in name:
        source_name, table_name = name.split(".", 1)
        for unique_id, source in manifest["sources"].items():
            if source["source_name"] == source_name and source["name"] == table_name:
                return unique_id

    print(f"No model or source named '{name}' found in the manifest.")
    sys.exit(1)


def downstream_closure(manifest: dict[str, Any], start_id: str) -> set[str]:
    """BFS over child_map to find every node transitively downstream of start_id."""
    child_map: dict[str, list[str]] = manifest["child_map"]
    visited: set[str] = set()
    queue = list(child_map.get(start_id, []))
    while queue:
        node_id = queue.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        queue.extend(child_map.get(node_id, []))
    return visited


def summarize(manifest: dict[str, Any], downstream_ids: set[str]) -> dict[str, list[str]]:
    """Group downstream unique_ids by resource_type, resolved to human-readable names."""
    groups: dict[str, list[str]] = {}
    for unique_id in downstream_ids:
        if unique_id in manifest["nodes"]:
            node = manifest["nodes"][unique_id]
            resource_type = node["resource_type"]
            name = node["name"]
        elif unique_id in manifest["exposures"]:
            resource_type = "exposure"
            name = manifest["exposures"][unique_id]["name"]
        else:
            resource_type = "other"
            name = unique_id
        groups.setdefault(resource_type, []).append(name)
    for names in groups.values():
        names.sort()
    return groups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="Model name, or 'schema.table' for a source")
    args = parser.parse_args()

    manifest = load_manifest()
    start_id = find_node_id(manifest, args.name)
    downstream_ids = downstream_closure(manifest, start_id)

    if not downstream_ids:
        print(f"{args.name}: nothing downstream.")
        return

    groups = summarize(manifest, downstream_ids)
    print(f"Impact of '{args.name}' breaking ({len(downstream_ids)} downstream node(s)):")
    for resource_type in ["model", "test", "exposure", "other"]:
        names = groups.get(resource_type)
        if not names:
            continue
        label = resource_type + ("s" if not resource_type.endswith("s") else "")
        print(f"  {label} ({len(names)}):")
        for name in names:
            print(f"    - {name}")


if __name__ == "__main__":
    main()
