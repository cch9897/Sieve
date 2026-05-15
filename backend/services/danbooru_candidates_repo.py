"""Repository for Danbooru candidates DB stats queries.

Encapsulates the read-only stats aggregations that back
``GET /api/danbooru/candidates/stats``. Operates on an already-opened
``sqlite3.Connection`` so the caller stays responsible for lifecycle.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any

SCORE_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.9, 1.01, "90-100%"),
    (0.8, 0.9, "80-90%"),
    (0.7, 0.8, "70-80%"),
    (0.6, 0.7, "60-70%"),
    (0.5, 0.6, "50-60%"),
    (0.0, 0.5, "<50%"),
)

HISTOGRAM_BINS = 40
Z95 = 1.96


class DanbooruCandidatesRepo:
    """Read-only stats helpers over ``candidates.db``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._cur = conn.cursor()

    def count_total(self) -> int:
        self._cur.execute("SELECT COUNT(*) FROM candidates")
        return self._cur.fetchone()[0]

    def count_pending(self) -> int:
        self._cur.execute("SELECT COUNT(*) FROM candidates WHERE status='pending'")
        return self._cur.fetchone()[0]

    def count_labeled(self) -> int:
        self._cur.execute("SELECT COUNT(*) FROM candidates WHERE status='labeled'")
        return self._cur.fetchone()[0]

    def count_by_score_bucket(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for lo, hi, label in SCORE_BUCKETS:
            self._cur.execute(
                "SELECT COUNT(*) FROM candidates WHERE preference_score >= ? AND preference_score < ?",
                (lo, hi),
            )
            cnt = self._cur.fetchone()[0]
            if cnt > 0:
                out[label] = cnt
        return out

    def count_by_rating(self) -> dict[str, int]:
        self._cur.execute("SELECT rating, COUNT(*) FROM candidates GROUP BY rating ORDER BY COUNT(*) DESC")
        return {r[0]: r[1] for r in self._cur.fetchall()}

    def avg_score(self) -> float:
        self._cur.execute("SELECT AVG(preference_score) FROM candidates")
        return self._cur.fetchone()[0] or 0

    def top_score(self) -> float:
        self._cur.execute("SELECT MAX(preference_score) FROM candidates")
        return self._cur.fetchone()[0] or 0

    def fetch_score_log(self) -> tuple[list[float], list[float], list[float]]:
        """Return (all_scores, accepted_scores, rejected_scores).

        Prefers ``score_log`` (every scored image) when populated; otherwise
        falls back to ``candidates.preference_score`` and treats every row as
        accepted (no rejected partition available in that fallback).
        """
        has_score_log = False
        try:
            self._cur.execute("SELECT COUNT(*) FROM score_log")
            has_score_log = (self._cur.fetchone()[0] or 0) > 0
        except sqlite3.OperationalError:
            has_score_log = False

        if has_score_log:
            self._cur.execute("SELECT fused_score, accepted FROM score_log WHERE fused_score IS NOT NULL")
            rows = self._cur.fetchall()
            all_scores = [r[0] for r in rows]
            accepted = [r[0] for r in rows if r[1] == 1]
            rejected = [r[0] for r in rows if r[1] == 0]
            return all_scores, accepted, rejected

        self._cur.execute("SELECT preference_score FROM candidates WHERE preference_score IS NOT NULL")
        all_scores = [r[0] for r in self._cur.fetchall()]
        return all_scores, all_scores, []

    @staticmethod
    def build_histogram(accepted_scores: list[float], rejected_scores: list[float]) -> list[dict[str, Any]]:
        bin_width = 1.0 / HISTOGRAM_BINS
        bin_accepted = [0] * HISTOGRAM_BINS
        bin_rejected = [0] * HISTOGRAM_BINS
        for s in accepted_scores:
            idx = min(int(s / bin_width), HISTOGRAM_BINS - 1)
            bin_accepted[idx] += 1
        for s in rejected_scores:
            idx = min(int(s / bin_width), HISTOGRAM_BINS - 1)
            bin_rejected[idx] += 1
        bins: list[dict[str, Any]] = []
        for i in range(HISTOGRAM_BINS):
            lo = round(i * bin_width, 4)
            hi = round((i + 1) * bin_width, 4)
            bins.append(
                {
                    "lo": lo,
                    "hi": hi,
                    "count": bin_accepted[i] + bin_rejected[i],
                    "accepted": bin_accepted[i],
                    "rejected": bin_rejected[i],
                }
            )
        return bins

    @staticmethod
    def confidence_stats(all_scores: list[float]) -> dict[str, Any]:
        n = len(all_scores)
        if n == 0:
            return {}
        if n == 1:
            v = round(all_scores[0], 4)
            return {
                "mean": v,
                "std": 0,
                "ci95_lo": v,
                "ci95_hi": v,
                "median": v,
                "p25": v,
                "p75": v,
                "p10": v,
                "p90": v,
                "n": 1,
            }
        mean = sum(all_scores) / n
        variance = sum((s - mean) ** 2 for s in all_scores) / (n - 1)
        std = math.sqrt(variance)
        se = std / math.sqrt(n)
        sorted_scores = sorted(all_scores)
        return {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "ci95_lo": round(max(mean - Z95 * se, 0), 4),
            "ci95_hi": round(min(mean + Z95 * se, 1), 4),
            "median": round(sorted_scores[n // 2], 4),
            "p25": round(sorted_scores[n // 4], 4),
            "p75": round(sorted_scores[3 * n // 4], 4),
            "p10": round(sorted_scores[n // 10], 4),
            "p90": round(sorted_scores[9 * n // 10], 4),
            "n": n,
        }
