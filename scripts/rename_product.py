#!/usr/bin/env python3
"""Centralized product rename: scripts/rename_product.py <new-name>

product.json is the single source of truth. This script:
  1. updates product.json (name, displayName, cli, marketplace)
  2. regenerates src/carrel/_product.py + pyproject version/description (sync_product)
  3. patches pyproject [project] name and the console-script entry name
  4. renames the CLI word `<old>` -> `<new>` in docs/plugins/snippets/examples
     (*.md, *.sh, *.json text files) and renames plugin directories
  5. leaves the Python package `carrel` untouched — imports stay stable;
     runtime display names come from _product.py

Run from anywhere; operates on the repo containing this script.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENAME_GLOBS = [
    "docs/**/*.md",
    "plugins/**/*.md",
    "plugins/**/*.json",
    "plugins/**/*.sh",
    "snippets/**",
    "examples/**",
    "tests/**/*.py",
    "README.md",
    "CHANGELOG.md",
    ".claude-plugin/marketplace.json",
    ".claude/agents/*.md",
    "specs/*.md",
]

# Core-owned literals that never rename (the Python package stays `carrel`):
# `.carrel/` desk dirs, `carrel.db`, module paths (carrel.core, from carrel import).
_PROTECTED = [
    ".carrel",
    "carrel.db",
    "carrel.cli",
    "carrel.core",
    "carrel.commands",
    "carrel.desk",
    "carrel._product",
    "import carrel",
    "from carrel",
]
_MASK = "\x00PROTECTED{}\x00"


def _rename_text(text: str, old: str, new: str) -> str:
    for i, token in enumerate(_PROTECTED):
        text = text.replace(token, _MASK.format(i))
    text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    for i, token in enumerate(_PROTECTED):
        text = text.replace(_MASK.format(i), token)
    return text


def patch_text_files(old: str, new: str) -> int:
    changed = 0
    for pattern in RENAME_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file() or path.suffix in {".png", ".jpg", ".ico", ".pdf"}:
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            new_text = _rename_text(text, old, new)
            if new_text != text:
                path.write_text(new_text)
                changed += 1
    return changed


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", sys.argv[1]):
        print("usage: rename_product.py <new-name>  (lowercase, cli-friendly)", file=sys.stderr)
        return 2
    new = sys.argv[1]

    product_path = ROOT / "product.json"
    product = json.loads(product_path.read_text())
    old = product["name"]
    if old == new:
        print(f"name already '{new}' — nothing to do")
        return 0

    product.update(name=new, displayName=new.capitalize(), cli=new, marketplace=new)
    product_path.write_text(json.dumps(product, indent=2, ensure_ascii=False) + "\n")

    # text references (CLI invocations in docs, plugins, snippets, examples)
    n = patch_text_files(old, new)

    # pyproject: project name + console-script key (module path stays carrel.cli:main)
    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text()
    text = re.sub(r'(?m)^name = ".*"$', f'name = "{new}"', text, count=1)
    text = re.sub(
        rf'(?m)^{re.escape(old)} = "carrel\.cli:main"$', f'{new} = "carrel.cli:main"', text, count=1
    )
    pyproject.write_text(text)

    # plugin directory names (plugins/carrel-convert -> plugins/<new>-convert)
    renamed_dirs = 0
    plugins_dir = ROOT / "plugins"
    if plugins_dir.is_dir():
        for child in sorted(plugins_dir.iterdir()):
            if child.is_dir() and old in child.name:
                child.rename(plugins_dir / child.name.replace(old, new))
                renamed_dirs += 1

    subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_product.py")], check=True)

    print(f"renamed {old} -> {new}: {n} text files patched, {renamed_dirs} plugin dirs renamed")
    print("note: the Python package/import name stays 'carrel' by design (see CLAUDE.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
