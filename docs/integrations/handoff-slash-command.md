---
description: Hand the current in-flight task off to a borina-mesh overnight worker
allowed-tools: Bash(git:*), Bash(curl:*), Read
---

You are handing off the user's current task to a borina-mesh overnight worker.

## Step 1: Gather context

Run these commands in parallel and capture output:
- `git rev-parse --show-toplevel` — get repo root
- `git rev-parse --abbrev-ref HEAD` — get current branch  
- `git status --porcelain` — get dirty state
- `git diff` — get unstaged changes

## Step 2: Build task description

From the user's request (passed as the command argument) and the most recent ~20 messages of this conversation, write a one-paragraph task description. Include any plan/spec the user has been working on.

## Step 3: POST to borina

```bash
curl -s -X POST http://localhost:8000/jobs/handoff \
  -H 'Content-Type: application/json' \
  -d '{
    "repo_path": "<repo root from step 1>",
    "base_branch": "<branch from step 1>",
    "prompt": "<task description from step 2>",
    "cwd_snapshot": "<git status output>",
    "diff_snapshot": "<git diff output, truncated to 5000 chars>",
    "recent_files": [<files touched in recent tool calls>],
    "conversation_tail": "<last 20 messages summarized in 500 words>"
  }'
```

## Step 4: Confirm

Print the returned `job_id` and `dashboard_url` to the user:

> Handed off as job #N — track at <dashboard_url>
