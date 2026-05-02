# routines/

Specs for the four autonomous routines that drive this repo. They could not
be created from the bootstrap session (the agent platform tool was not
available at install time). When you return, install them via either:

(a) the `RemoteTrigger` Anthropic Managed Agents API, OR
(b) `mcp__scheduled-tasks__create_scheduled_task` (local cron).

Each `*.routine.yml` file is the prompt + cron in a copy/paste-ready form.

## Files

- `kickoff.routine.yml` — one-shot, fires immediately on install.
- `daily_calibration.routine.yml` — `0 3 * * *` UTC, ~50min/run.
- `intraday_scan.routine.yml` — `0 * * * *` UTC, every hour 24/7, 15min/run.
- `asset_rotation.routine.yml` — `0 */4 * * *` UTC, every 4h, 30min/run.

## Install via RemoteTrigger

For each yml file:

```python
RemoteTrigger.create(
    environment_id="env_01PkjZM61nLK8yvWynh7pdWG",
    model="claude-sonnet-4-6",
    sources=[{"git_repository": {"url": "https://github.com/SennaSemakula/crypto_research_watchlist"}}],
    allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
    cron_expression=<from yml>,             # omit for kickoff
    fire_at=<for kickoff: now + 120s>,
    events=[{"data": {"uuid": "<fresh-v4>"}}],
    prompt=<from yml>,
)
```

Generate a fresh v4 UUID per routine.

## Hard rules baked into every prompt

- NO Telegram, NO live trades, NO paid APIs.
- yfinance + ccxt public endpoints only.
- Direct push to `main`. No PRs.
- If `src/` is touched, run pytest first; do not push if any test fails.
- A `.agent_panic` file at the repo root halts execution.
