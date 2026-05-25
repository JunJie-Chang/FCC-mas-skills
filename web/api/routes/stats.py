"""
web/api/routes/stats.py — Aggregate stats for the dashboard.

Single endpoint /stats/summary returns everything the homepage needs
in one request — cheaper than 4 separate queries and keeps the
dashboard render cleanly synchronous from the UI side.

Counts the parent Job rows only. STT pipeline parents have already
aggregated their sub-task costs into their own cost_usd in
job_runner.py, so listing sub-tasks separately would double-count.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from web.api.db import get_session
from web.api.models import Job, JobStatus
from web.api.schemas import JobResponse

router = APIRouter(prefix="/stats", tags=["stats"])


class CostByTypeRow(BaseModel):
    type: str
    cost_usd: float
    count: int


class StatusCountRow(BaseModel):
    status: str
    count: int


class DailyCostRow(BaseModel):
    date: str       # YYYY-MM-DD
    cost_usd: float
    count: int


class StatsSummary(BaseModel):
    window_days:        int
    total_cost_usd:     float
    job_count:          int
    cost_by_type:       list[CostByTypeRow]
    counts_by_status:   list[StatusCountRow]
    cost_trend_daily:   list[DailyCostRow]
    recent_jobs:        list[JobResponse]


@router.get("/summary", response_model=StatsSummary)
def get_summary(
    db: Session = Depends(get_session),
    days: int = Query(30, ge=1, le=365),
) -> StatsSummary:
    """
    Snapshot for the dashboard. `days` controls the rolling window
    for cost / count aggregations and the trend chart; recent_jobs
    always returns the last 5 regardless of window.
    """
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(days=days)

    in_window = (
        db.query(Job)
        .filter(Job.created_at >= window_start)
        .all()
    )

    total_cost = sum(j.cost_usd for j in in_window)

    # Cost + count by type
    cost_by_type: dict[str, float] = defaultdict(float)
    count_by_type: dict[str, int] = Counter()
    for j in in_window:
        cost_by_type[j.type] += j.cost_usd
        count_by_type[j.type] += 1
    cost_rows = sorted(
        (CostByTypeRow(type=t, cost_usd=cost_by_type[t], count=count_by_type[t])
         for t in cost_by_type),
        key=lambda r: -r.cost_usd,
    )

    # Counts by status
    status_counts: Counter[str] = Counter(j.status.value for j in in_window)
    status_rows = [
        StatusCountRow(status=s.value, count=status_counts.get(s.value, 0))
        for s in JobStatus
        # Only include statuses that have any rows — keeps the dashboard
        # legend short. Always include `done` and `failed` for context.
        if status_counts.get(s.value, 0) > 0 or s in (JobStatus.DONE, JobStatus.FAILED)
    ]

    # Daily trend — bucket by date (in UTC; close enough for IB
    # working hours, and switching to Asia/Taipei would just rotate
    # the boundary by 8h).
    daily_cost: dict[str, float] = defaultdict(float)
    daily_count: dict[str, int] = Counter()
    for j in in_window:
        day = j.created_at.astimezone(timezone.utc).date().isoformat()
        daily_cost[day] += j.cost_usd
        daily_count[day] += 1

    # Fill missing days with zeros so the chart isn't jagged.
    trend: list[DailyCostRow] = []
    for d_offset in range(days):
        day = (now_utc - timedelta(days=days - 1 - d_offset)).date().isoformat()
        trend.append(DailyCostRow(
            date=day,
            cost_usd=daily_cost.get(day, 0.0),
            count=daily_count.get(day, 0),
        ))

    recent = (
        db.query(Job)
        .order_by(Job.created_at.desc())
        .limit(5)
        .all()
    )

    return StatsSummary(
        window_days       = days,
        total_cost_usd    = total_cost,
        job_count         = len(in_window),
        cost_by_type      = cost_rows,
        counts_by_status  = status_rows,
        cost_trend_daily  = trend,
        recent_jobs       = recent,
    )
