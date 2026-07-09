# -*- coding: utf-8 -*-
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DATA_PATHS = (
    "audition_emoji_replace.json",
    "audition_stickers/",
)


def run_git(args):
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").splitlines()


def staged_files():
    return run_git(["diff", "--cached", "--name-only"])


def touches_data(paths):
    normalized = [path.replace("\\", "/") for path in paths]
    for path in normalized:
        if path == "audition_emoji_replace.json":
            return True
        if path.startswith("audition_stickers/"):
            return True
    return False


def next_data_version():
    return datetime.now().strftime("%Y.%m.%d.%H%M%S")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    paths = staged_files()
    if not touches_data(paths):
        return 0

    data_version = next_data_version()

    metadata_path = Path("app_metadata.json")
    manifest_path = Path("update_manifest.json")

    metadata = load_json(metadata_path)
    metadata["data_version"] = data_version
    save_json(metadata_path, metadata)

    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    manifest["latest_data_version"] = data_version
    manifest.setdefault(
        "data_zip_url",
        "https://github.com/RootOfGenius/VibeKey/archive/refs/heads/main.zip",
    )
    manifest.setdefault("notes", ["Data package update."])
    manifest["reload_required"] = True
    manifest["restart_required"] = False
    manifest["allowed_paths"] = [
        "audition_emoji_replace.json",
        "audition_stickers/",
    ]
    save_json(manifest_path, manifest)

    subprocess.check_call(["git", "add", "app_metadata.json", "update_manifest.json"])
    print(f"[pre-commit] Bumped data_version to {data_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
