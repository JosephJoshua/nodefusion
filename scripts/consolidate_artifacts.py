"""Join reports and videos from the same archived run into one artifact set.

Only the repository's known chapter/app paths are selected. Distinct runs stay
separate even when they share a chapter or showcase directory.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.regenerate_artifact import sha256, smoke_report


def _write(path: Path, value: dict) -> None:
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _report(path: Path, html: Path) -> dict:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if evidence["schema"] != "nodefusion.artifact-evidence/1":
        raise ValueError(f"unexpected report evidence: {path}")
    if sha256(html) != evidence["html_sha256"]:
        raise ValueError(f"HTML hash mismatch: {html}")
    if smoke_report(html)["meta"]["capability"]["coverage"] != evidence["coverage"]:
        raise ValueError(f"coverage mismatch: {html}")
    return evidence


def _video_pair(video_path: Path, evidence_path: Path) -> dict:
    video = json.loads(video_path.read_text(encoding="utf-8"))
    if video.get("format") != "nodefusion.video-evidence/1" or "report" in video:
        raise ValueError(f"unexpected video sidecar: {video_path}")
    html = video_path.with_name(video["html"])
    evidence = _report(evidence_path, html)
    if ((video.get("info") or {}).get("runs") != [evidence["run"]]
            or video["info"].get("kernel_elf_sha256") != evidence["kernel_elf_sha256"]
            or video_path.with_name(video["mp4"]).stat().st_size != video["bytes"]
            or sha256(video_path.with_name(video["mp4"])) != video["mp4_sha256"]):
        raise ValueError(f"video and report are not the same archived run: {video_path}")
    video["report"] = evidence
    return video


def merge_video(video_path: Path, evidence_path: Path) -> None:
    video = _video_pair(video_path, evidence_path)
    _write(video_path, video)
    evidence_path.unlink()


def _ucore_pair(coverage_path: Path, evidence_path: Path, html: Path) -> dict:
    old = json.loads(coverage_path.read_text(encoding="utf-8"))["chapter"]
    evidence = _report(evidence_path, html)
    if (old["run"] != evidence["run"]
            or old["trace_sha256"] != evidence["source_sha256"]["trace.nfb"]
            or old["kernel_elf_sha256"] != evidence["kernel_elf_sha256"]):
        raise ValueError(f"chapter evidence is from a different trace: {coverage_path}")
    return evidence


def merge_ucore(coverage_path: Path, evidence_path: Path, html: Path) -> None:
    evidence = _ucore_pair(coverage_path, evidence_path, html)
    _write(coverage_path, evidence)
    evidence_path.unlink()


def consolidate(root: Path) -> None:
    video_pairs = []
    for chapter in (1, 2, 3, 4, 5, 6, 8):
        folder = root / "rcore" / f"ch{chapter}"
        name = {1: "bare", 2: "batch", 3: "sched", 4: "exact",
                5: "exact", 6: "usertest", 8: "exact-filetest"}[chapter]
        stem = f"rcore-ch{chapter}-{name}"
        video_pairs.append((folder / f"{stem}.json", folder / f"{stem}.evidence.json"))
    for app in ("forkecho", "fsprobe"):
        folder = root / "starryos" / "apps" / app
        stem = f"starry-{app}-ram512"
        video_pairs.append((folder / f"{stem}.json", folder / f"{stem}.evidence.json"))
    chapter_pairs = []
    for chapter in range(1, 9):
        folder = root / "ucoreos" / f"ch{chapter}"
        evidence_files = list(folder.glob("ucore-*.evidence.json"))
        if len(evidence_files) != 1:
            raise ValueError(f"expected one chapter report: {folder}")
        evidence_path = evidence_files[0]
        chapter_pairs.append((folder / "coverage.json", evidence_path,
                              folder / (evidence_path.name.removesuffix(".evidence.json") + ".html")))
    # Validate the whole known set before writing any sidecar.
    videos = [_video_pair(*pair) for pair in video_pairs]
    chapters = [_ucore_pair(*pair) for pair in chapter_pairs]
    for (video_path, evidence_path), video in zip(video_pairs, videos):
        _write(video_path, video)
        evidence_path.unlink()
    for (coverage_path, evidence_path, _), chapter in zip(chapter_pairs, chapters):
        _write(coverage_path, chapter)
        evidence_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    consolidate(args.root)


if __name__ == "__main__":
    main()
