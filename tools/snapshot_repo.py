#!/usr/bin/env python3
import argparse
import datetime as dt
import os
from pathlib import Path

# ---------- настройки ----------
EXCLUDE_DIRS = {
    ".git", ".idea", ".vscode", "__pycache__", "node_modules", "venv",
    ".mypy_cache", ".pytest_cache", ".DS_Store",
}
EXCLUDE_EXT = {
    ".sqlite3", ".sqlite", ".pyc", ".log"
}
# какие файлы кода включать в CODE_SNAPSHOT
CODE_GLOBS = [
    "backend/manage.py",
    "backend/sales_portal/settings.py",
    "backend/sales_portal/urls.py",
    "backend/sales_portal/wsgi.py",
    "backend/sales_portal/asgi.py",

    "backend/sales/apps.py",
    "backend/sales/models.py",
    "backend/sales/admin.py",
    "backend/sales/urls.py",
    "backend/sales/views_api.py",
    "backend/sales/views_pages.py",
    "backend/sales/forms.py",

    "backend/sales/importers/*.py",
    "backend/sales/services/*.py",
    "backend/sales/tests.py",

    # шаблоны
    "backend/templates/**/*.html",
]

# ---------- утилиты ----------
def project_root() -> Path:
    # tools/snapshot_repo.py -> SalesPortal/
    return Path(__file__).resolve().parents[1]

def is_ignored(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if path.suffix in EXCLUDE_EXT:
        return True
    return False

def build_tree(root: Path) -> str:
    lines = []
    def walk(base: Path, prefix=""):
        entries = sorted([p for p in base.iterdir() if not is_ignored(p)],
                         key=lambda p: (p.is_file(), p.name.lower()))
        for i, p in enumerate(entries):
            last = (i == len(entries) - 1)
            connector = "└── " if last else "├── "
            lines.append(prefix + connector + p.name)
            if p.is_dir():
                ext = "    " if last else "│   "
                walk(p, prefix + ext)
    walk(root)
    return "\n".join(lines)

def expand_globs(root: Path, patterns):
    out = []
    for pat in patterns:
        out.extend(sorted(root.glob(pat)))
    # убрать дубликаты и игноры
    uniq = []
    seen = set()
    for p in out:
        if is_ignored(p):
            continue
        rp = p.resolve()
        if rp not in seen and rp.exists() and rp.is_file():
            uniq.append(p)
            seen.add(rp)
    return uniq

# ---------- main ----------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="перезаписать файлы за сегодня (без добавления времени)")
    args = parser.parse_args()

    ROOT = project_root()               # .../SalesPortal
    BACKEND = ROOT / "backend"

    now = dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M-%S")

    # имена файлов
    if args.force:
        tree_name = f"PROJECT_TREE_{date_str}.txt"
        code_name = f"CODE_SNAPSHOT_{date_str}.md"
    else:
        tree_name = f"PROJECT_TREE_{date_str}_{time_str}.txt"
        code_name = f"CODE_SNAPSHOT_{date_str}_{time_str}.md"

    tree_path = ROOT / tree_name
    code_path = ROOT / code_name

    # --- дерево проекта (от корня репозитория) ---
    tree = build_tree(ROOT)
    tree_path.write_text(tree, encoding="utf-8")
    print(f"[OK] Project tree -> {tree_path.relative_to(ROOT)}")

    # --- код-дамп основных файлов ---
    files = expand_globs(ROOT, CODE_GLOBS)
    with code_path.open("w", encoding="utf-8") as f:
        f.write(f"# Code snapshot ({now.isoformat(timespec='seconds')})\n\n")
        for p in files:
            rel = p.relative_to(ROOT)
            f.write(f"\n\n---\n\n## `{rel}`\n\n```{p.suffix.lstrip('.') or 'text'}\n")
            try:
                f.write(p.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                f.write("<binary or non-utf8 file omitted>")
            f.write("\n```\n")
    print(f"[OK] Code snapshot -> {code_path.relative_to(ROOT)}")

if __name__ == "__main__":
    main()
