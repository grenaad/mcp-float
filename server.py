"""Float MCP Server - Manage time entries on Float.com via MCP tools.

Exposes tools for:
- Listing projects assigned to the authenticated user
- Listing logged time entries
- Bulk-creating time entries for a month
- Creating single time entries
- Deleting time entries
- Verifying authentication
- Calculating workdays
"""

import calendar
import logging
from datetime import date

from fastmcp import FastMCP

from float_client import FloatClient, FloatClientError
from models import (
    AuthResponse,
    CreateEntriesResponse,
    CreateSingleEntryResponse,
    DeleteEntryResponse,
    ErrorResponse,
    LoggedTime,
    Project,
    ProjectRow,
    ProjectSummary,
    TimeEntriesResponse,
    TimeEntryInput,
    TimeEntryRow,
    WorkdaysResponse,
)
from utils import get_holidays_for_month, get_workdays_for_month

logger = logging.getLogger(__name__)

mcp = FastMCP("Float Time Tracker")

# Lazily-initialized client (created on first tool call)
_client: FloatClient | None = None


async def _get_client() -> FloatClient:
    """Get or create an authenticated Float client."""
    global _client
    if _client is None:
        _client = FloatClient()
        await _client.login()
    return _client


def _to_entry_row(entry: LoggedTime, holiday: str = "") -> TimeEntryRow:
    """Convert a full LoggedTime to a compact TimeEntryRow."""
    return TimeEntryRow(
        id=entry.logged_time_id,
        date=entry.date,
        hours=entry.hours,
        project=entry.project_name,
        notes=entry.notes,
        holiday=holiday,
    )


def _to_project_row(project: Project) -> ProjectRow:
    """Convert a full Project to a compact ProjectRow."""
    return ProjectRow(
        project_id=project.project_id,
        name=project.name,
    )


@mcp.tool
async def list_projects() -> list[ProjectRow]:
    """List Float projects assigned to the authenticated user.

    Returns only projects the user can log time to, sorted by name.
    """
    client = await _get_client()
    projects = await client.get_my_projects()
    projects.sort(key=lambda p: p.name)
    return [_to_project_row(p) for p in projects]


@mcp.tool
async def list_time_entries(
    year: int,
    month: int,
) -> TimeEntriesResponse | ErrorResponse:
    """List logged time entries for a given month/year, grouped by project.

    Returns entries sorted by date, with a per-project summary and totals.
    Automatically filters to the authenticated user.

    Args:
        year: The year (e.g. 2025).
        month: The month number (1-12).
    """
    if month < 1 or month > 12:
        return ErrorResponse(error=f"Month must be between 1 and 12, got: {month}")

    client = await _get_client()
    people_id = client.people_id

    first_day = date(year, month, 1)
    _, days_in_month = calendar.monthrange(year, month)
    last_day = date(year, month, days_in_month)

    entries = await client.get_logged_time_entries(
        first_day.isoformat(), last_day.isoformat()
    )

    # Resolve project names
    projects = await client.get_projects()
    project_map = {p.project_id: p.name for p in projects}

    for entry in entries:
        entry.project_name = project_map.get(
            entry.project_id, f"Unknown ({entry.project_id})"
        )

    # Filter to the authenticated user and exclude deleted (0h) entries
    entries = [e for e in entries if e.people_id == people_id and e.hours > 0]

    month_name = calendar.month_name[month]

    if not entries:
        return TimeEntriesResponse(
            message=f"No logged time entries for {month_name} {year}",
        )

    # Sort by date then project name
    entries.sort(key=lambda e: (e.date, e.project_name))

    # Build per-project summary
    summaries: dict[int, ProjectSummary] = {}
    total_hours = 0.0

    for entry in entries:
        pid = entry.project_id
        if pid not in summaries:
            summaries[pid] = ProjectSummary(
                project_id=pid,
                project_name=entry.project_name,
                entry_count=0,
                total_hours=0.0,
            )
        summaries[pid].entry_count += 1
        summaries[pid].total_hours += entry.hours
        total_hours += entry.hours

    # Annotate entries that fall on SA public holidays
    month_holidays = get_holidays_for_month(year, month)

    return TimeEntriesResponse(
        message=f"Logged time entries for {month_name} {year}",
        entries=[
            _to_entry_row(e, holiday=month_holidays.get(e.date, "")) for e in entries
        ],
        summary=list(summaries.values()),
        total_entries=len(entries),
        total_hours=total_hours,
    )


@mcp.tool
async def create_time_entries(
    year: int,
    month: int,
    project_id: int,
    hours: float,
    phase_id: int = 0,
    task_meta_id: int = 0,
    notes: str = "",
) -> CreateEntriesResponse | ErrorResponse:
    """Bulk-create time entries for all workdays (Mon-Fri) in a given month.

    Creates one entry per workday for the specified project, logged under
    the authenticated user.

    Args:
        year: The year (e.g. 2025).
        month: The month number (1-12).
        project_id: The Float project ID.
        hours: Hours per day to log.
        phase_id: Optional phase ID (default 0).
        task_meta_id: Optional task meta ID (default 0).
        notes: Optional notes for the entries.
    """
    if month < 1 or month > 12:
        return ErrorResponse(error=f"Month must be between 1 and 12, got: {month}")

    client = await _get_client()
    people_id = client.people_id

    workdays = get_workdays_for_month(year, month)

    entries = [
        TimeEntryInput(
            hours=hours,
            people_id=people_id,
            project_id=project_id,
            phase_id=phase_id,
            date=day,
            task_meta_id=task_meta_id,
            notes=notes,
        )
        for day in workdays
    ]

    try:
        created = await client.create_time_entries(entries)
    except FloatClientError as e:
        return ErrorResponse(error=str(e))

    month_name = calendar.month_name[month]

    return CreateEntriesResponse(
        message=f"Created {len(created)} time entries for {month_name} {year}",
        workdays_count=len(workdays),
        entries_created=len(created),
    )


@mcp.tool
async def create_single_entry(
    date_str: str,
    project_id: int,
    hours: float,
    phase_id: int = 0,
    task_meta_id: int = 0,
    notes: str = "",
) -> CreateSingleEntryResponse | ErrorResponse:
    """Create a single time entry for a specific date.

    Logs under the authenticated user.

    Args:
        date_str: The date in YYYY-MM-DD format.
        project_id: The Float project ID.
        hours: Hours to log.
        phase_id: Optional phase ID (default 0).
        task_meta_id: Optional task meta ID (default 0).
        notes: Optional notes for the entry.
    """
    client = await _get_client()
    people_id = client.people_id

    entry = TimeEntryInput(
        hours=hours,
        people_id=people_id,
        project_id=project_id,
        phase_id=phase_id,
        date=date_str,
        task_meta_id=task_meta_id,
        notes=notes,
    )

    try:
        created = await client.create_time_entries([entry])
    except FloatClientError as e:
        return ErrorResponse(error=str(e))

    if not created:
        return ErrorResponse(error="No time entry was created")

    created_entry = created[0]
    # Resolve project name
    projects = await client.get_projects()
    project_map = {p.project_id: p.name for p in projects}
    created_entry.project_name = project_map.get(
        created_entry.project_id, f"Unknown ({created_entry.project_id})"
    )

    return CreateSingleEntryResponse(
        message=f"Created time entry for {date_str}",
        entry=_to_entry_row(created_entry),
    )


@mcp.tool
async def delete_time_entry(
    logged_time_id: str,
) -> DeleteEntryResponse | ErrorResponse:
    """Delete a time entry by its logged_time_id.

    Use list_time_entries to find the logged_time_id of the entry you
    want to delete.

    Args:
        logged_time_id: The ID of the logged time entry to delete.
    """
    client = await _get_client()

    try:
        await client.delete_time_entry(logged_time_id)
    except FloatClientError as e:
        return ErrorResponse(error=str(e))

    return DeleteEntryResponse(
        message=f"Deleted time entry {logged_time_id}",
        logged_time_id=logged_time_id,
    )


@mcp.tool
async def verify_auth() -> AuthResponse:
    """Verify that Float credentials are valid and return session context.

    Tests the authentication flow without making any data changes.
    Returns the authenticated user's info and the projects they can
    log time to, so you know what project_id values to use with other tools.
    """
    try:
        client = await _get_client()
        projects = await client.get_my_projects()
        projects.sort(key=lambda p: p.name)
        return AuthResponse(
            status="ok",
            message="Authentication successful",
            account_name=client.account_name,
            people_id=client.people_id,
            company=client.company_name,
            projects=[_to_project_row(p) for p in projects],
        )
    except FloatClientError as e:
        return AuthResponse(
            status="error",
            message=f"Authentication failed: {e}",
        )


@mcp.tool
async def get_workdays(year: int, month: int) -> WorkdaysResponse | ErrorResponse:
    """Get all working days (Mon-Fri) for a given month.

    Args:
        year: The year (e.g. 2025).
        month: The month number (1-12).

    Returns:
        The month name, count, and list of date strings in YYYY-MM-DD format.
    """
    if month < 1 or month > 12:
        return ErrorResponse(error=f"Month must be between 1 and 12, got: {month}")

    workdays = get_workdays_for_month(year, month)
    month_holidays = get_holidays_for_month(year, month)
    month_name = calendar.month_name[month]

    return WorkdaysResponse(
        month=f"{month_name} {year}",
        workday_count=len(workdays),
        workdays=workdays,
        holidays=month_holidays,
    )


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
