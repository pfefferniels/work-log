# Reading Claude Code cloud sessions

Notes from 2026-09-26. The endpoints are undocumented and in beta, so they may change.

## Listing sessions

`GET https://api.anthropic.com/v1/code/sessions?limit=100`

Headers:

```
Authorization: Bearer <OAuth access token>
anthropic-version: 2023-06-01
anthropic-beta: ccr-byoc-2025-07-29
```

The token is in the macOS keychain, entry `Claude Code-credentials`, field `claudeAiOauth.accessToken`:

```sh
TOKEN=$(security find-generic-password -s "Claude Code-credentials" -w \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["claudeAiOauth"]["accessToken"])')
```

Each entry has `id` (`cse_…`), `title`, `status` and `status_bucket` (e.g. `working`, `blocked`, `completed`), `created_at`, `updated_at`, `last_event_at`, the repos and branches under `config.outcomes`, the model under `config.model`, and usage and cost under `external_metadata`.

When more sessions exist than `limit`, the response carries `next_cursor`, which goes back as `?cursor=…`. A request with `limit=5` returned one; a request with `limit=100` returned 20 sessions and none, so 20 was the full list at the time. Paging through with the cursor to the end has not been tried. The `resume_token` field is not a page cursor: passed as `cursor`, it is rejected as invalid.

## Reading a transcript

`GET /v1/code/sessions/{id}/events` returns a condensed log: user and assistant messages, tool calls and results, with timestamps. It gives the newest events first, 50 per page by default and up to at least 200 with `limit`. The response's `next_cursor` (a sequence number) goes back as `?cursor=…` for the next older page. Long entries are truncated and thinking is hidden. Both `cse_…` and the `session_…` ID from the claude.ai URL work.

Each event has `event_type`, `created_at`, `sequence_num` and a `payload`. `user` and `assistant` payloads carry a `message` shaped like the one in local transcripts, plus `timestamp` and `parent_tool_use_id` (set inside subagents). Besides those there are `system`, `result` and `tool_progress` events from the worker, and `control_request` and `prompt_suggestion` events that appear when someone opens the session page. The latter two can arrive hours after the work and say nothing about it.

Inside Claude Code, the `RemoteTrigger` tool can call this without handling the token (`action: get_run_log`, `session_id`). It is meant for routine runs but works for any session. Its `list_runs` action needs a routine ID, so listing all sessions requires the direct call above.

`ListAgents` and `claude agents --json` show only local sessions.
