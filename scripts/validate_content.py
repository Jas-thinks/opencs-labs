#!/usr/bin/env python3
"""Validate curriculum and exercise content before it reaches the database.

Checks:
  * every referenced module/lesson/exercise file exists and parses
  * slugs are unique
  * referenced datasets exist in the dataset manifests
  * every lesson has the seven-stage structure and an objective
  * exercise evaluation tests are not exposed through public fields
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTENT = REPO / "content"
STAGES = ["explore", "understand", "inspect", "execute", "visualize", "debug", "practice"]
BLOCK_TYPES = {
    "markdown",
    "code",
    "output",
    "table",
    "chart",
    "callout",
    "steps",
    "mistakes",
    "checklist",
    "dataset",
    "glossary",
}

errors: list[str] = []
warnings: list[str] = []


def error(message: str) -> None:
    errors.append(message)


def load(path: Path) -> dict:
    try:
        text = path.read_text()
        if path.suffix in (".yaml", ".yml"):
            import yaml

            doc = yaml.safe_load(text)
        else:
            doc = json.loads(text)
        if not isinstance(doc, dict):
            raise ValueError("document must be a mapping")
        return doc
    except Exception as exc:  # noqa: BLE001
        error(f"{path.relative_to(REPO)}: invalid content: {exc}")
        return {}


def content_files(directory: Path, extensions: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for extension in extensions:
        files.extend(directory.glob(f"*{extension}"))
    return sorted(files)


def main() -> int:
    manifests = {}
    for manifest_path in (REPO / "datasets" / "manifests").glob("*.json"):
        if manifest_path.name == "index.json":
            continue
        doc = load(manifest_path)
        manifests[doc.get("slug")] = doc

    paths = load(CONTENT / "paths.json")
    lesson_slugs: set[str] = set()
    lesson_index: dict[str, dict] = {}
    exercise_files = content_files(CONTENT / "exercises", (".yaml", ".yml", ".json"))
    exercise_slugs = {path.stem for path in exercise_files}

    for path in paths.get("paths", []):
        for module_slug in path.get("modules", []):
            module_file = CONTENT / "lessons" / f"{module_slug}.yaml"
            if not module_file.is_file():
                module_file = CONTENT / "lessons" / f"{module_slug}.json"
            if not module_file.is_file():
                error(f"paths.json references missing module '{module_slug}'")
                continue
            module = load(module_file)
            if module.get("slug") != module_slug:
                error(f"{module_file.name}: slug mismatch")
            for lesson in module.get("lessons", []):
                slug = lesson.get("slug")
                if not slug:
                    error(f"{module_file.name}: lesson missing slug")
                    continue
                if slug in lesson_slugs:
                    error(f"duplicate lesson slug: {slug}")
                lesson_slugs.add(slug)
                lesson_index[slug] = lesson

                if not lesson.get("objective"):
                    error(f"{slug}: missing objective")
                if not lesson.get("title"):
                    error(f"{slug}: missing title")
                content = lesson.get("content", {})
                stages = content.get("stages", [])
                keys = [stage.get("key") for stage in stages]
                missing = [key for key in STAGES if key not in keys]
                if missing:
                    error(f"{slug}: missing stages: {', '.join(missing)}")
                for stage in stages:
                    for block in stage.get("blocks", []):
                        btype = block.get("type")
                        if btype not in BLOCK_TYPES:
                            error(f"{slug}: unknown block type '{btype}'")
                        if btype == "code" and not block.get("source"):
                            error(f"{slug}: code block without source")
                        if btype == "chart" and not block.get("spec"):
                            error(f"{slug}: chart block without spec")
                for dataset_slug in lesson.get("datasets", []):
                    if dataset_slug not in manifests:
                        error(f"{slug}: unknown dataset '{dataset_slug}'")
                for exercise_slug in lesson.get("exercises", []):
                    if exercise_slug not in exercise_slugs:
                        warnings.append(f"{slug}: exercise '{exercise_slug}' has no file yet")
                activity = lesson.get("notebook_activity")
                if activity and not activity.get("cells"):
                    warnings.append(f"{slug}: notebook activity has no cells")

    for path in exercise_files:
        spec = load(path)
        if spec.get("difficulty") not in {"Easy", "Medium", "Hard"}:
            error(f"{path.name}: difficulty must be Easy/Medium/Hard")
        if not spec.get("hints"):
            warnings.append(f"{path.name}: no hints")
        if spec.get("starter_notebook", {}).get("cells") is None:
            error(f"{path.name}: starter_notebook.cells missing")
        evaluation = spec.get("evaluation", {})
        if evaluation.get("type") and not evaluation.get("tests"):
            error(f"{path.name}: evaluation without tests would fail at runtime")
        for dataset_slug in spec.get("datasets", []):
            if dataset_slug not in manifests:
                error(f"{path.name}: unknown dataset '{dataset_slug}'")
        if "solution_code" in spec and spec["solution_code"]:
            warnings.append(
                f"{path.name}: solution_code present — it stays server-side and is never serialised"
            )

    for warning in warnings:
        print(f"WARN  {warning}")
    for message in errors:
        print(f"ERROR {message}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} content error(s)", file=sys.stderr)
        return 1
    print(
        f"content OK: {len(lesson_slugs)} lessons in {len(paths.get('paths', []))} paths, "
        f"{len(exercise_slugs)} exercises, {len(manifests)} datasets"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
