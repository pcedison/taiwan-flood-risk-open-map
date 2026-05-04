from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "docs" / "runbooks" / "flood-potential-import.example.yaml"
WORK_DIR = REPO_ROOT / "tmp" / "flood-potential-import"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_flood_potential_import import validate_manifest_file  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan or run a flood-potential SHP import from a validated manifest.",
    )
    parser.add_argument(
        "manifest_path",
        nargs="?",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Flood-potential import manifest path.",
    )
    parser.add_argument(
        "--source-archive",
        help="Local SHP directory, .shp file, or .zip archive that was recorded in the manifest.",
    )
    parser.add_argument(
        "--output",
        help="Output PMTiles path, MVT directory, or PostGIS layer name depending on manifest output_format.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostGIS connection string for output_format=postgis. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--work-dir",
        default=str(WORK_DIR),
        help="Working directory for intermediate GeoJSONSeq output.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the planned commands without running conversion tools.",
    )
    parser.add_argument(
        "--require-tools",
        action="store_true",
        help="In dry-run mode, fail when required conversion tools are missing.",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest_path)
    errors = validate_manifest_file(manifest_path)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    manifest = _load_manifest(manifest_path)
    output_format = str(manifest["processing"]["output_format"])
    source_archive = Path(args.source_archive).resolve() if args.source_archive else None
    output = args.output or str(manifest["processing"]["output_ref"])
    plan = build_import_plan(
        output_format=output_format,
        source_archive=source_archive,
        output=output,
        database_url=args.database_url,
        work_dir=Path(args.work_dir),
    )

    tool_errors = missing_tool_errors(plan.required_tools)
    if args.dry_run:
        print_import_plan(plan)
        if args.require_tools and tool_errors:
            for error in tool_errors:
                print(error, file=sys.stderr)
            return 1
        return 0

    if source_archive is None:
        print("--source-archive is required when not using --dry-run", file=sys.stderr)
        return 1
    if not source_archive.exists():
        print(f"source archive/path not found: {source_archive}", file=sys.stderr)
        return 1
    if tool_errors:
        for error in tool_errors:
            print(error, file=sys.stderr)
        return 1

    plan.work_dir.mkdir(parents=True, exist_ok=True)
    for command in plan.commands:
        subprocess.run(command, check=True)
    print(f"Flood-potential import completed: {output}")
    return 0


class ImportPlan:
    def __init__(
        self,
        *,
        output_format: str,
        source: str,
        output: str,
        work_dir: Path,
        required_tools: tuple[str, ...],
        commands: tuple[tuple[str, ...], ...],
    ) -> None:
        self.output_format = output_format
        self.source = source
        self.output = output
        self.work_dir = work_dir
        self.required_tools = required_tools
        self.commands = commands


def build_import_plan(
    *,
    output_format: str,
    source_archive: Path | None,
    output: str,
    database_url: str | None,
    work_dir: Path,
) -> ImportPlan:
    source = gdal_source_path(source_archive) if source_archive is not None else "<source-archive>"
    intermediate = work_dir / "flood-potential.geojsonseq"
    if output_format == "pmtiles":
        return ImportPlan(
            output_format=output_format,
            source=source,
            output=output,
            work_dir=work_dir,
            required_tools=("ogr2ogr", "tippecanoe"),
            commands=(
                ("ogr2ogr", "-t_srs", "EPSG:4326", "-f", "GeoJSONSeq", str(intermediate), source),
                (
                    "tippecanoe",
                    "-o",
                    output,
                    "--force",
                    "--layer",
                    "flood_potential",
                    str(intermediate),
                ),
            ),
        )
    if output_format == "mvt":
        return ImportPlan(
            output_format=output_format,
            source=source,
            output=output,
            work_dir=work_dir,
            required_tools=("ogr2ogr", "tippecanoe"),
            commands=(
                ("ogr2ogr", "-t_srs", "EPSG:4326", "-f", "GeoJSONSeq", str(intermediate), source),
                (
                    "tippecanoe",
                    "--output-to-directory",
                    output,
                    "--force",
                    "--layer",
                    "flood_potential",
                    str(intermediate),
                ),
            ),
        )
    if output_format == "postgis":
        if not database_url:
            database_url = "<DATABASE_URL>"
        return ImportPlan(
            output_format=output_format,
            source=source,
            output=output,
            work_dir=work_dir,
            required_tools=("ogr2ogr",),
            commands=(
                (
                    "ogr2ogr",
                    "-t_srs",
                    "EPSG:4326",
                    "-f",
                    "PostgreSQL",
                    f"PG:{database_url}",
                    source,
                    "-nln",
                    output,
                    "-overwrite",
                ),
            ),
        )
    raise ValueError(f"unsupported output_format: {output_format}")


def gdal_source_path(source_archive: Path) -> str:
    if source_archive.suffix.casefold() == ".zip":
        return f"/vsizip/{source_archive}"
    return str(source_archive)


def missing_tool_errors(required_tools: tuple[str, ...]) -> list[str]:
    return [
        f"required conversion tool not found on PATH: {tool}"
        for tool in required_tools
        if shutil.which(tool) is None
    ]


def print_import_plan(plan: ImportPlan) -> None:
    print(f"Flood-potential import plan: {plan.output_format}")
    print(f"source: {plan.source}")
    print(f"output: {plan.output}")
    print(f"work_dir: {plan.work_dir}")
    print(f"required_tools: {', '.join(plan.required_tools)}")
    for index, command in enumerate(plan.commands, start=1):
        print(f"command_{index}: {_shell_join(command)}")


def _load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError("manifest must be an object")
    return payload


def _shell_join(command: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(part) for part in command)


if __name__ == "__main__":
    raise SystemExit(main())
