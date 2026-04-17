"""Pydantic domain models for Float time entries and projects."""

from __future__ import annotations

from pydantic import BaseModel


# ── Domain models (internal, full API fields) ───────────────────────


class TimeEntryInput(BaseModel):
    """Input model for creating a time entry."""

    hours: float
    people_id: int
    project_id: int
    phase_id: int = 0
    date: str
    task_meta_id: int = 0
    notes: str = ""


class LoggedTime(BaseModel):
    """Full time entry as returned from Float's API."""

    logged_time_id: str = ""
    people_id: int = 0
    task_meta_id: int = 0
    task_id: int | None = None
    date: str = ""
    reference_date: str | None = None
    hours: float = 0.0
    notes: str = ""
    priority: int = 0
    modified: str = ""
    modified_by: int = 0
    created: str = ""
    created_by: int = 0
    task_name: str = ""
    project_id: int = 0
    phase_id: int = 0
    billable: int = 0
    company_id: int = 0
    notes_meta: str | None = None
    locked: int = 0
    locked_date: str | None = None
    project_name: str = ""


class Project(BaseModel):
    """A Float project (full API fields)."""

    project_id: int
    name: str
    people_ids: list[int] = []


# ── Slim response models (LLM-facing) ──────────────────────────────


class TimeEntryRow(BaseModel):
    """Compact time entry for tool responses."""

    id: str
    date: str
    hours: float
    project: str
    notes: str = ""
    holiday: str = ""


class ProjectRow(BaseModel):
    """Compact project for tool responses."""

    project_id: int
    name: str


# ── Session cache ───────────────────────────────────────────────────


class SessionCache(BaseModel):
    """Cached session data for avoiding re-authentication."""

    jwt_token: str = ""
    jwt_expiry: int = 0
    notify_uuid: str = ""
    session_cookie: str = ""
    session_expiry: str = ""
    csrf_cookie: str = ""
    gclb_cookie: str = ""
    people_id: int = 0
    account_name: str = ""
    company_name: str = ""


# ── Tool response models ───────────────────────────────────────────


class ErrorResponse(BaseModel):
    """Returned when a tool encounters an error."""

    error: str


class AuthResponse(BaseModel):
    """Returned by verify_auth with session context."""

    status: str
    message: str
    account_name: str = ""
    people_id: int = 0
    company: str = ""
    projects: list[ProjectRow] = []


class ProjectSummary(BaseModel):
    """Per-project summary within a time entries response."""

    project_id: int
    project_name: str
    entry_count: int
    total_hours: float


class TimeEntriesResponse(BaseModel):
    """Returned by list_time_entries."""

    message: str
    entries: list[TimeEntryRow] = []
    summary: list[ProjectSummary] = []
    total_entries: int = 0
    total_hours: float = 0.0


class CreateEntriesResponse(BaseModel):
    """Returned by create_time_entries."""

    message: str
    workdays_count: int
    entries_created: int


class CreateSingleEntryResponse(BaseModel):
    """Returned by create_single_entry."""

    message: str
    entry: TimeEntryRow


class DeleteEntryResponse(BaseModel):
    """Returned by delete_time_entry."""

    message: str
    logged_time_id: str


class WorkdaysResponse(BaseModel):
    """Returned by get_workdays."""

    month: str
    workday_count: int
    workdays: list[str]
    holidays: dict[str, str] = {}
