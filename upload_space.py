"""
upload_space.py — Upload api/ to HF Space, excluding venv and cache dirs.
Run from project root: python upload_space.py
"""
import os
from pathlib import Path
from huggingface_hub import HfApi

REPO_ID = "ujwwal/quietcost-api"
API_DIR = Path(__file__).parent / "api"

IGNORE_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", "calibration/__pycache__", "loaders/__pycache__", "pipeline/__pycache__"}
IGNORE_EXTS = {".pyc", ".pyo"}

api = HfApi()
uploaded = 0

for filepath in API_DIR.rglob("*"):
    if not filepath.is_file():
        continue
    # Skip ignored dirs
    parts = set(filepath.relative_to(API_DIR).parts[:-1])
    if parts & IGNORE_DIRS or filepath.suffix in IGNORE_EXTS:
        continue
    # Skip __pycache__ anywhere in path
    if "__pycache__" in str(filepath):
        continue
    if ".venv" in str(filepath):
        continue

    rel_path = filepath.relative_to(API_DIR)
    posix_path = rel_path.as_posix()   # always forward slashes for HF Hub
    print(f"  uploading: {posix_path}")
    api.upload_file(
        path_or_fileobj=str(filepath),
        path_in_repo=posix_path,
        repo_id=REPO_ID,
        repo_type="space",
    )
    uploaded += 1

print(f"\nDone! Uploaded {uploaded} files to https://huggingface.co/spaces/{REPO_ID}")
