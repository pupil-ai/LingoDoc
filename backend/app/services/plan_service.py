import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PlanLimits:
    plan: str
    max_pages_per_file: int
    max_file_size_mb: int
    monthly_page_quota: int
    free_preview_pages: int

    @property
    def is_unlimited_pages(self) -> bool:
        return self.max_pages_per_file <= 0


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


PLAN_LIMITS = {
    "free": PlanLimits(
        plan="free",
        max_pages_per_file=_read_int_env("FREE_MAX_PAGES_PER_FILE", 3),
        max_file_size_mb=_read_int_env("FREE_MAX_FILE_SIZE_MB", 25),
        monthly_page_quota=_read_int_env("FREE_MONTHLY_PAGE_QUOTA", 0),
        free_preview_pages=_read_int_env("FREE_PREVIEW_PAGE_LIMIT", 3),
    ),
    "starter": PlanLimits(
        plan="starter",
        max_pages_per_file=_read_int_env("STARTER_MAX_PAGES_PER_FILE", 50),
        max_file_size_mb=_read_int_env("STARTER_MAX_FILE_SIZE_MB", 50),
        monthly_page_quota=_read_int_env("STARTER_MONTHLY_PAGE_QUOTA", 500),
        free_preview_pages=0,
    ),
    "pro": PlanLimits(
        plan="pro",
        max_pages_per_file=_read_int_env("PRO_MAX_PAGES_PER_FILE", 300),
        max_file_size_mb=_read_int_env("PRO_MAX_FILE_SIZE_MB", 100),
        monthly_page_quota=_read_int_env("PRO_MONTHLY_PAGE_QUOTA", 3000),
        free_preview_pages=0,
    ),
    "power": PlanLimits(
        plan="power",
        max_pages_per_file=_read_int_env("POWER_MAX_PAGES_PER_FILE", 3000),
        max_file_size_mb=_read_int_env("POWER_MAX_FILE_SIZE_MB", 250),
        monthly_page_quota=_read_int_env("POWER_MONTHLY_PAGE_QUOTA", 30000),
        free_preview_pages=0,
    ),
}

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
DEFAULT_PLAN = os.getenv("DEFAULT_USER_PLAN", "free").strip().lower() or "free"


def normalize_plan(plan: Optional[str], subscription_status: Optional[str] = None) -> str:
    normalized_plan = (plan or DEFAULT_PLAN).strip().lower()
    if normalized_plan not in PLAN_LIMITS:
        normalized_plan = "free"

    if normalized_plan == "free":
        return normalized_plan

    normalized_status = (subscription_status or "").strip().lower()
    if normalized_status not in ACTIVE_SUBSCRIPTION_STATUSES:
        return "free"

    return normalized_plan


def get_plan_limits(plan: Optional[str], subscription_status: Optional[str] = None) -> PlanLimits:
    return PLAN_LIMITS[normalize_plan(plan, subscription_status)]


def get_translatable_page_count(total_pages: int, limits: PlanLimits) -> int:
    if total_pages <= 0:
        return 0

    if limits.plan == "free":
        page_limit = limits.free_preview_pages if limits.free_preview_pages > 0 else total_pages
        return min(total_pages, page_limit)

    if limits.is_unlimited_pages:
        return total_pages

    return min(total_pages, limits.max_pages_per_file)


def get_max_file_size_bytes(limits: PlanLimits) -> int:
    if limits.max_file_size_mb <= 0:
        return 0

    return limits.max_file_size_mb * 1024 * 1024
