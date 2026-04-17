# float-mcp

MCP server for Float.com time entry management — exposes time tracking tools to AI coding agents via the Model Context Protocol using stdio transport.

## Setup

```bash
cp .env.sample .env  # fill in your Float credentials
uv venv .venv
uv pip install -r pyproject.toml
```

## Claude Desktop

Add to the config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "float": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/float/mcp", "fastmcp", "run", "server.py:mcp"],
      "env": {
        "FLOAT_EMAIL": "your-email@example.com",
        "FLOAT_PASSWORD": "your-password"
      }
    }
  }
}
```

## Claude Code

### CLI

```bash
claude mcp add --transport stdio --scope user float -- \
  uv run --directory /absolute/path/to/float/mcp fastmcp run server.py:mcp
```

Then set the environment variables in `~/.claude/settings.json` under the server entry.

### Manual

In `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "float": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/float/mcp", "fastmcp", "run", "server.py:mcp"],
      "env": {
        "FLOAT_EMAIL": "your-email@example.com",
        "FLOAT_PASSWORD": "your-password"
      }
    }
  }
}
```

## OpenCode

In `opencode.jsonc` (project root or global config):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "float": {
      "type": "local",
      "command": ["uv", "run", "--directory", "/absolute/path/to/float/mcp", "fastmcp", "run", "server.py:mcp"],
      "environment": {
        "FLOAT_EMAIL": "your-email@example.com",
        "FLOAT_PASSWORD": "your-password"
      }
    }
  }
}
```

## Tools

| Tool                  | Description                                                    |
| --------------------- | -------------------------------------------------------------- |
| `list_projects`       | List all Float projects                                        |
| `list_time_entries`   | List logged time entries for a month, grouped by project       |
| `create_time_entries` | Bulk-create time entries for all workdays (Mon-Fri) in a month |
| `create_single_entry` | Create a single time entry for a specific date                 |
| `delete_time_entry`   | Delete a specific time entry by ID                             |
| `verify_auth`         | Verify credentials without making changes (dry run)            |
| `get_workdays`        | Calculate working days (Mon-Fri) for a given month             |

## Environment Variables

| Variable              | Required | Default                                 |
| --------------------- | -------- | --------------------------------------- |
| `FLOAT_EMAIL`         | Yes      | —                                       |
| `FLOAT_PASSWORD`      | Yes      | —                                       |
| `FLOAT_BASE_URL`      | No       | `https://justsolve-solutions.float.com` |
| `FLOAT_SESSION_CACHE` | No       | `~/.float-session.json`                 |

## Project Structure

```
mcp/
├── server.py           # FastMCP server entry point (7 tools)
├── float_client.py     # Async HTTP client with 4-step auth flow
├── models.py           # Pydantic domain models
├── config.py           # Environment variable configuration
├── utils.py            # Workday calculation helpers
└── pyproject.toml      # Python project metadata & dependencies
```
