"""Explicit per-channel scheduler approval; paused is not operational acceptance."""
from __future__ import annotations

import os
from pathlib import Path


def decide(event: str, dry_run: str, enabled: str) -> tuple[str, bool, int]:
    if event not in {"schedule", "workflow_dispatch"}:
        return "blocked_unknown_event", False, 1
    if event == "workflow_dispatch" and dry_run == "true":
        return "read_only", True, 0
    if event == "workflow_dispatch" and dry_run != "false":
        return "blocked_invalid_manual_mode", False, 1
    if enabled.strip().lower() == "true":
        return "approved_live", True, 0
    return ("paused", False, 0) if event == "schedule" else ("blocked_unapproved_live", False, 1)


def main() -> int:
    mode, run, code = decide(os.getenv("GITHUB_EVENT_NAME", ""),
                             os.getenv("DRY_RUN", ""), os.getenv("CHANNEL_ENABLED", ""))
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"run={str(run).lower()}\nmode={mode}\n")
    message = {
        "paused": "Messaging schedule paused: channel approval flag is not true. No API calls, messages or database writes performed.",
        "read_only": "Read-only manual check: no messages or database writes. This does not establish delivery acceptance.",
        "approved_live": "Workflow channel approval present. Server safeguards and credentials are still required.",
    }.get(mode, "Dispatch blocked: unapproved live run or invalid mode. No sending authorized.")
    print(message)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(f"### Messaging gate: {mode}\n\n{message}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
