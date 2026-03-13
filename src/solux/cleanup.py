from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
import time

from .config import Config
from .queueing import prune_jobs


@dataclass(frozen=True)
class CleanupTarget:
    path: Path
    kind: str
    source_id: str | None
    file_count_hint: int
    size_bytes: int


def _count_files_and_size(path: Path) -> tuple[int, int]:
    file_count = 0
    size_bytes = 0
    for item in path.rglob("*"):
        if item.is_file():
            file_count += 1
            try:
                size_bytes += item.stat().st_size
            except OSError:
                pass
    return file_count, size_bytes


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def _iter_source_dirs(cache_dir: Path, source_id: str | None = None) -> list[Path]:
    sources_dir = cache_dir / "sources"
    if not sources_dir.exists():
        return []

    dirs: list[Path]
    if source_id:
        candidate = sources_dir / source_id
        if candidate.exists() and candidate.is_dir():
            dirs = [candidate]
        else:
            dirs = []
    else:
        dirs = sorted(p for p in sources_dir.iterdir() if p.is_dir())
    return dirs


def _is_result_file(path: Path) -> bool:
    return path.name == "transcript.txt" or path.name.startswith("summary-")


def _is_metadata_file(path: Path) -> bool:
    return path.name == "metadata.json"


def _is_finished_source(source_dir: Path) -> bool:
    for item in source_dir.iterdir():
        if item.is_file() and _is_result_file(item):
            return True
    return False


def _source_last_update(source_dir: Path) -> float:
    last = 0.0
    for item in source_dir.iterdir():
        if item.is_file() and (_is_result_file(item) or _is_metadata_file(item)):
            try:
                last = max(last, item.stat().st_mtime)
            except OSError:
                pass
    if last == 0.0:
        try:
            last = source_dir.stat().st_mtime
        except OSError:
            last = 0.0
    return last


def _collect_all_targets(cache_dir: Path, source_id: str | None) -> list[CleanupTarget]:
    targets: list[CleanupTarget] = []
    for source_dir in _iter_source_dirs(cache_dir, source_id):
        file_count, size_bytes = _count_files_and_size(source_dir)
        targets.append(
            CleanupTarget(
                path=source_dir,
                kind="source_dir",
                source_id=source_dir.name,
                file_count_hint=file_count,
                size_bytes=size_bytes,
            )
        )
    outputs_dir = cache_dir / "outputs"
    if outputs_dir.exists() and outputs_dir.is_dir() and source_id is None:
        file_count, size_bytes = _count_files_and_size(outputs_dir)
        if file_count:
            targets.append(
                CleanupTarget(
                    path=outputs_dir,
                    kind="outputs_dir",
                    source_id=None,
                    file_count_hint=file_count,
                    size_bytes=size_bytes,
                )
            )
    return targets


def _collect_artifact_targets(cache_dir: Path, source_id: str | None) -> list[CleanupTarget]:
    targets: list[CleanupTarget] = []
    for source_dir in _iter_source_dirs(cache_dir, source_id):
        for item in source_dir.iterdir():
            if not item.is_file():
                continue
            if _is_result_file(item) or _is_metadata_file(item):
                continue
            try:
                size_bytes = item.stat().st_size
            except OSError:
                size_bytes = 0
            targets.append(
                CleanupTarget(
                    path=item,
                    kind="artifact_file",
                    source_id=source_dir.name,
                    file_count_hint=1,
                    size_bytes=size_bytes,
                )
            )
    return targets


def _collect_finished_targets(
    cache_dir: Path,
    source_id: str | None,
    older_than_days: int | None,
) -> list[CleanupTarget]:
    targets: list[CleanupTarget] = []
    threshold = None
    if older_than_days is not None:
        threshold = time.time() - (older_than_days * 86400)

    for source_dir in _iter_source_dirs(cache_dir, source_id):
        if not _is_finished_source(source_dir):
            continue
        if threshold is not None and _source_last_update(source_dir) >= threshold:
            continue
        file_count, size_bytes = _count_files_and_size(source_dir)
        targets.append(
            CleanupTarget(
                path=source_dir,
                kind="finished_source_dir",
                source_id=source_dir.name,
                file_count_hint=file_count,
                size_bytes=size_bytes,
            )
        )

    outputs_dir = cache_dir / "outputs"
    if outputs_dir.exists() and outputs_dir.is_dir():
        for target in list(targets):
            if not target.source_id:
                continue
            for item in outputs_dir.glob(f"*-{target.source_id}-*"):
                if not item.is_file():
                    continue
                try:
                    size_bytes = item.stat().st_size
                except OSError:
                    size_bytes = 0
                targets.append(
                    CleanupTarget(
                        path=item,
                        kind="finished_export",
                        source_id=target.source_id,
                        file_count_hint=1,
                        size_bytes=size_bytes,
                    )
                )
    return targets


def _remove_empty_dirs_under(source_dir: Path) -> None:
    # Remove nested empty directories, keeping the root source dir unless empty.
    for child in sorted(source_dir.rglob("*"), reverse=True):
        if child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass
    try:
        source_dir.rmdir()
    except OSError:
        pass


def run_cleanup(
    config: Config,
    *,
    source_id: str | None = None,
    yes: bool = False,
    dry_run: bool = False,
    artifacts_only: bool = False,
    finished_only: bool = False,
    older_than_days: int | None = None,
    jobs: bool = False,
    jobs_stale_only: bool = False,
    jobs_all_statuses: bool = False,
) -> int:
    if jobs and (artifacts_only or finished_only or older_than_days is not None):
        print("Error: --jobs cannot be combined with file cleanup flags")
        return 1
    if artifacts_only and finished_only:
        print("Error: use only one of --artifacts-only or --finished-only")
        return 1
    if older_than_days is not None and older_than_days < 0:
        print("Error: --older-than-days must be >= 0")
        return 1
    if older_than_days is not None and not finished_only:
        print("Error: --older-than-days requires --finished-only")
        return 1
    if jobs_stale_only and not jobs:
        print("Error: --jobs-stale-only requires --jobs")
        return 1
    if jobs_all_statuses and not jobs:
        print("Error: --jobs-all-statuses requires --jobs")
        return 1

    if jobs:
        statuses = (
            {"pending", "processing", "done", "failed", "dead_letter"}
            if jobs_all_statuses
            else {"done", "failed", "dead_letter"}
        )
        source_label = f" for source_id={source_id}" if source_id else ""
        stale_label = " stale-only" if jobs_stale_only else ""
        print(f"Queue cleanup scope: statuses={','.join(sorted(statuses))}{stale_label}{source_label}")
        if dry_run:
            # Dry-run for queue jobs: read and count using prune filters without writing by simulating.
            from .queueing import read_jobs

            all_jobs = read_jobs(config.paths.cache_dir)
            remove_count = 0
            for job in all_jobs:
                status = str(job.get("status", ""))
                if status not in statuses:
                    continue
                if source_id and str(job.get("source_id", "")) != source_id:
                    continue
                if jobs_stale_only:
                    sid = str(job.get("source_id") or "").strip()
                    if not sid or (config.paths.cache_dir / "sources" / sid).exists():
                        continue
                remove_count += 1
            print(f"Dry run only. Would remove {remove_count} queue job(s), leaving {len(all_jobs) - remove_count}.")
            return 0

        if not yes:
            choice = input("Delete matching queue jobs? [y/N]: ").strip().lower()
            if choice not in {"y", "yes"}:
                print("Cleanup cancelled.")
                return 0

        stats = prune_jobs(
            config.paths.cache_dir,
            statuses=statuses,
            source_id=source_id,
            stale_only=jobs_stale_only,
        )
        print(f"Removed {stats['removed']} queue job(s). Remaining: {stats['remaining']}.")
        return 0

    cache_dir = config.paths.cache_dir
    if artifacts_only:
        targets = _collect_artifact_targets(cache_dir, source_id=source_id)
        scope = "processing artifacts"
    elif finished_only:
        targets = _collect_finished_targets(
            cache_dir,
            source_id=source_id,
            older_than_days=older_than_days,
        )
        scope = "finished outputs"
    else:
        targets = _collect_all_targets(cache_dir, source_id=source_id)
        scope = "all cached source data"

    if not targets:
        if source_id:
            print(f"No cleanup targets found for source_id '{source_id}' in {cache_dir}")
        else:
            print(f"No cleanup targets found in {cache_dir}")
        return 0

    print(f"Cache directory: {cache_dir}")
    print(f"Scope: {scope}")
    print("Targets:")
    total_files = sum(t.file_count_hint for t in targets)
    total_size = sum(t.size_bytes for t in targets)
    for target in targets:
        source_meta = f" [source_id={target.source_id}]" if target.source_id else ""
        print(
            f"- ({target.kind}) {target.path}{source_meta} "
            f"({target.file_count_hint} files, {_human_size(target.size_bytes)})"
        )
    print(f"Total: {len(targets)} targets, {total_files} files, {_human_size(total_size)}")

    if dry_run:
        print("Dry run only. No files were deleted.")
        return 0

    if not yes:
        choice = input("Delete these targets? [y/N]: ").strip().lower()
        if choice not in {"y", "yes"}:
            print("Cleanup cancelled.")
            return 0

    failures = 0
    for target in targets:
        try:
            if target.path.is_dir():
                shutil.rmtree(target.path)
            elif target.path.exists():
                target.path.unlink()
            if target.kind == "artifact_file" and target.source_id:
                source_dir = cache_dir / "sources" / target.source_id
                if source_dir.exists():
                    _remove_empty_dirs_under(source_dir)
            print(f"Deleted: {target.path}")
        except OSError as exc:
            failures += 1
            print(f"Failed to delete {target.path}: {exc}")

    if failures:
        print(f"Cleanup completed with {failures} failure(s).")
        return 1

    print("Cleanup completed.")
    return 0
