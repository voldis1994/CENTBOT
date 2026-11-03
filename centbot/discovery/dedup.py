"""Duplicate task filtering."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


def normalize_title(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s]", "", t)
    return t


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


class DuplicateFilter:
    def __init__(self, threshold: float = 0.92):
        self.threshold = threshold

    def filter(self, tasks: list[dict[str, Any]], known_fingerprints: set[str] | None = None) -> list[dict[str, Any]]:
        known = set(known_fingerprints or [])
        kept: list[dict[str, Any]] = []
        for task in tasks:
            fp = task.get("fingerprint") or ""
            if fp and fp in known:
                continue
            dup = False
            for other in kept:
                if task.get("platform") == other.get("platform") and task.get("external_id") == other.get("external_id"):
                    dup = True
                    break
                if similar(task.get("title", ""), other.get("title", "")) >= self.threshold:
                    # Same-ish title and similar reward => duplicate
                    if abs(float(task.get("reward_amount") or 0) - float(other.get("reward_amount") or 0)) < 0.01:
                        dup = True
                        break
            if dup:
                continue
            kept.append(task)
            if fp:
                known.add(fp)
        return kept
