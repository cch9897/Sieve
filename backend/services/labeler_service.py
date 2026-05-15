"""Shared service layer for labeler routers.

Both ``labeler`` (local crawler images) and ``danbooru_labeler`` (DanbooruFinder
proxy) expose the same shape of CRUD endpoints over different SQLite databases
and slightly different ``labels`` schemas. This module encapsulates the common
SQL so the routers only carry their domain-specific glue (cross-DB joins,
vision-score sources, remote downloads).

The service operates on already-acquired ``aiosqlite.Connection`` objects so
each router stays in charge of pool management — we don't import from
``database`` here to avoid a service↔️database circular reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import aiosqlite


@dataclass(frozen=True)
class LabelerConfig:
    """Configuration describing one labeler database / table.

    Attributes:
        labels_table: name of the labels table (always ``labels`` today).
        tags_table: name of the user-tags table (always ``tags`` today).
        extra_label_columns: ordered list of extra column names persisted on
            insert/upsert beside ``image_id`` and ``verdict``. Empty for the
            local labeler, ``["ext", "score", "rating", "tags"]`` for danbooru.
    """

    labels_table: str = "labels"
    tags_table: str = "tags"
    extra_label_columns: tuple[str, ...] = field(default_factory=tuple)


# Pre-built configs for the two existing routers.
LOCAL_LABELER = LabelerConfig()
DANBOORU_LABELER = LabelerConfig(extra_label_columns=("ext", "score", "rating", "tags"))


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def apply_label(
    db: aiosqlite.Connection,
    cfg: LabelerConfig,
    image_id: int,
    verdict: str,
    user_tags: Optional[list[str]] = None,
    extra_values: Optional[dict] = None,
) -> None:
    """Upsert a label row and optionally append user tags.

    ``extra_values`` carries the danbooru-only columns (ext / score / rating /
    tags). Keys not in ``cfg.extra_label_columns`` are ignored so callers can
    pass their full request dict without filtering.
    """
    cols = ["image_id", "verdict"]
    vals: list = [image_id, verdict]
    for col in cfg.extra_label_columns:
        cols.append(col)
        vals.append((extra_values or {}).get(col, ""))
    cols.append("updated_at")
    placeholders = ", ".join(["?"] * (len(cols) - 1) + ["CURRENT_TIMESTAMP"])
    update_cols = [c for c in cols if c not in ("image_id",)]
    update_clause = ", ".join(
        f"{c}=excluded.{c}" if c != "updated_at" else "updated_at=CURRENT_TIMESTAMP" for c in update_cols
    )
    sql = (
        f"INSERT INTO {cfg.labels_table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(image_id) DO UPDATE SET {update_clause}"
    )
    await db.execute(sql, vals)

    if user_tags:
        clean = [(image_id, t.strip()) for t in user_tags if t.strip()]
        if clean:
            await db.executemany(
                f"INSERT OR IGNORE INTO {cfg.tags_table} (image_id, tag) VALUES (?, ?)",
                clean,
            )

    await db.commit()


async def remove_label(
    db: aiosqlite.Connection,
    cfg: LabelerConfig,
    image_id: int,
) -> None:
    """Delete the label row and any associated user tags."""
    await db.execute(f"DELETE FROM {cfg.labels_table} WHERE image_id = ?", [image_id])
    await db.execute(f"DELETE FROM {cfg.tags_table} WHERE image_id = ?", [image_id])
    await db.commit()


async def replace_user_tags(
    db: aiosqlite.Connection,
    cfg: LabelerConfig,
    image_id: int,
    tags: list[str],
) -> None:
    """Replace the user-tag set for one image."""
    await db.execute(f"DELETE FROM {cfg.tags_table} WHERE image_id = ?", [image_id])
    clean = [(image_id, t.strip()) for t in tags if t.strip()]
    if clean:
        await db.executemany(
            f"INSERT OR IGNORE INTO {cfg.tags_table} (image_id, tag) VALUES (?, ?)",
            clean,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


async def fetch_verdict_counts(
    db: aiosqlite.Connection,
    cfg: LabelerConfig,
) -> dict[str, int]:
    """Return ``{liked, disliked, skipped, total_labeled}`` counts."""
    counts = {"liked": 0, "disliked": 0, "skipped": 0}
    async with db.execute(f"SELECT verdict, COUNT(*) FROM {cfg.labels_table} GROUP BY verdict") as c:
        for row in await c.fetchall():
            counts[row[0]] = row[1]
    counts["total_labeled"] = counts["liked"] + counts["disliked"] + counts["skipped"]
    return counts


async def fetch_top_user_tags(
    db: aiosqlite.Connection,
    cfg: LabelerConfig,
    limit: int = 50,
) -> list[dict]:
    """Top-N rows from the user tags table."""
    async with db.execute(
        f"SELECT tag, COUNT(*) AS cnt FROM {cfg.tags_table} GROUP BY tag ORDER BY cnt DESC LIMIT ?",
        [limit],
    ) as c:
        return [{"tag": r[0], "count": r[1]} for r in await c.fetchall()]


async def fetch_history_page(
    db: aiosqlite.Connection,
    cfg: LabelerConfig,
    *,
    select_columns: str,
    verdict: Optional[str],
    tag: Optional[str],
    page: int,
    per_page: int,
) -> tuple[int, list]:
    """Return ``(total, rows)`` for one page of label history.

    ``select_columns`` is the column list on the labels table prefixed with
    ``l.`` so the router controls which extra columns it needs (the danbooru
    one selects ``ext / score / rating / tags`` while the local labeler does
    not). Filtering by verdict / tag is identical between routers.
    """
    conditions = ["1=1"]
    params: list = []
    if verdict:
        conditions.append("l.verdict = ?")
        params.append(verdict)
    if tag:
        conditions.append(f"l.image_id IN (SELECT image_id FROM {cfg.tags_table} WHERE tag = ?)")
        params.append(tag)
    where = " AND ".join(conditions)
    offset = (page - 1) * per_page

    async with db.execute(f"SELECT COUNT(*) FROM {cfg.labels_table} l WHERE {where}", params) as c:
        total = (await c.fetchone())[0]

    async with db.execute(
        f"SELECT {select_columns} FROM {cfg.labels_table} l WHERE {where} ORDER BY l.updated_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ) as c:
        rows = await c.fetchall()
    return total, rows


async def fetch_user_tags_map(
    db: aiosqlite.Connection,
    cfg: LabelerConfig,
    image_ids: list[int],
) -> dict[int, list[str]]:
    """Return ``{image_id: [tag, ...]}`` for the given ids."""
    if not image_ids:
        return {}
    placeholders = ",".join("?" * len(image_ids))
    async with db.execute(
        f"SELECT image_id, tag FROM {cfg.tags_table} WHERE image_id IN ({placeholders})",
        image_ids,
    ) as c:
        rows = await c.fetchall()
    out: dict[int, list[str]] = {}
    for r in rows:
        out.setdefault(r[0], []).append(r[1])
    return out


async def fetch_export_targets(
    db: aiosqlite.Connection,
    cfg: LabelerConfig,
    *,
    select_columns: str,
    verdict: str,
    tag: Optional[str],
) -> list:
    """Resolve which labels match an export request.

    ``select_columns`` mirrors ``fetch_history_page`` — caller picks columns.
    """
    conditions = ["l.verdict = ?"]
    params: list = [verdict]
    if tag:
        conditions.append(f"l.image_id IN (SELECT image_id FROM {cfg.tags_table} WHERE tag = ?)")
        params.append(tag)
    where = " AND ".join(conditions)
    async with db.execute(f"SELECT {select_columns} FROM {cfg.labels_table} l WHERE {where}", params) as c:
        return list(await c.fetchall())
