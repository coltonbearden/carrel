#!/usr/bin/env python3
"""Regenerate every derived copy of product identity from /product.json.

product.json is the single source of truth for product identity (see CLAUDE.md).
Run after editing product.json; finalize.sh runs it during rename. Writes:

- src/<package>/_product.py          (runtime copy; the wheel never ships product.json)
- pyproject.toml                     (version, description, [project.urls])
- .claude-plugin/marketplace.json    (each plugin entry's version)
- plugins/*/.claude-plugin/plugin.json (version)
- CITATION.cff                       (version, date-released, repository URLs)

tests/test_product_sync.py and tests/test_marketplace.py assert all of these
agree with product.json, so a version bump that skips this script fails CI.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _sub_line(text: str, key: str, value: str) -> str:
    """Replace the first `key = "..."` line at column 0 (TOML) with a new value."""
    pattern = rf'(?m)^{re.escape(key)} = ".*"$'
    if not re.search(pattern, text):
        raise SystemExit(f"pyproject.toml: no top-level line `{key} = ...` to update")
    return re.sub(pattern, f'{key} = "{value}"', text, count=1)


def sync_pyproject(product: dict[str, str]) -> None:
    path = ROOT / "pyproject.toml"
    text = path.read_text()
    text = _sub_line(text, "version", product["version"])
    text = _sub_line(text, "description", f"{product['tagline']} {product['description']}")

    repo = product["repository"]
    owner_repo = repo.removeprefix("https://github.com/")
    owner = owner_repo.split("/", 1)[0]
    urls = (
        "[project.urls]\n"
        f'Homepage = "https://{owner}.github.io/{product["name"]}/"\n'
        f'Documentation = "https://{owner}.github.io/{product["name"]}/"\n'
        f'Repository = "{repo}"\n'
        f'Changelog = "{repo}/blob/main/CHANGELOG.md"\n'
        f'Issues = "{repo}/issues"\n'
    )
    block = re.compile(r"(?ms)^\[project\.urls\]\n(?:^[^\[\n][^\n]*\n)*")
    if block.search(text):
        text = block.sub(urls, text, count=1)
    else:
        text = text.replace("\n[project.scripts]", f"\n{urls}\n[project.scripts]", 1)
    path.write_text(text)


def sync_json_version(path: Path, version: str) -> None:
    """Rewrite every `"version": "..."` field in a manifest, preserving its formatting."""
    text = path.read_text()
    pattern = re.compile(r'(?m)^(\s*"version":\s*)"[^"]*"')
    if not pattern.search(text):
        raise SystemExit(f"{path}: no version field to update")
    path.write_text(pattern.sub(lambda m: f'{m.group(1)}"{version}"', text))


def sync_citation(product: dict[str, str]) -> None:
    path = ROOT / "CITATION.cff"
    if not path.is_file():
        return
    text = path.read_text()
    today = dt.datetime.now(dt.UTC).date().isoformat()
    if re.search(rf'(?m)^version: "{re.escape(product["version"])}"$', text) is None:
        text = re.sub(r'(?m)^date-released: ".*"$', f'date-released: "{today}"', text, count=1)
    text = re.sub(r'(?m)^version: ".*"$', f'version: "{product["version"]}"', text, count=1)
    text = re.sub(
        r'(?m)^repository-code: ".*"$', f'repository-code: "{product["repository"]}"', text, count=1
    )
    text = re.sub(r'(?m)^url: ".*"$', f'url: "{product["repository"]}"', text, count=1)
    text = re.sub(r'(?m)^title: ".*"$', f'title: "{product["name"]}"', text, count=1)
    path.write_text(text)


def main() -> int:
    product = json.loads((ROOT / "product.json").read_text())

    gen = ROOT / "src" / product["package"] / "_product.py"
    gen.write_text(
        '"""GENERATED from /product.json by scripts/sync_product.py — do not edit."""\n\n'
        f"PRODUCT = {json.dumps(product, indent=4, ensure_ascii=False)}\n"
    )

    sync_pyproject(product)
    sync_json_version(ROOT / ".claude-plugin" / "marketplace.json", product["version"])
    for manifest in sorted(ROOT.glob("plugins/*/.claude-plugin/plugin.json")):
        sync_json_version(manifest, product["version"])
    sync_citation(product)

    print(
        f"synced: {product['name']} v{product['version']} -> {gen.relative_to(ROOT)}, "
        "pyproject.toml, marketplace + plugin manifests, CITATION.cff"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
