# Instagram AI Analyzer & Growth Engine — Constitution (STARTER DRAFT)

> ⚠️ **DRAFT — starter principles distilled from the spec/plan decisions.** This is *not* ratified.
> Review, edit, and formally adopt it (or replace it) by running the **speckit-constitution** skill.
> Once ratified, these principles become the non-negotiable authority for the project.

## Core Principles

### I. Code-First Automation
The automation layer is a **Python application** (Docker: `cron` + `bot`), not a visual tool. Logic
must be **testable and diffable** as code. Visual/no-code tools are rejected for this pipeline.

### II. Idempotent & Safe-to-Retry (NON-NEGOTIABLE)
Every job **upserts on natural keys**; re-running a failed job produces identical state. No partial
side effects. `pipeline_runs.run_id` is the idempotency/dedup key for delivery.

### III. Secrets Hygiene (NON-NEGOTIABLE)
Secrets live **only** in `pydantic-settings` env (Docker secrets) or Supabase Vault — never in code,
commits, or logs. No DB table stores secrets. Least-privilege API scopes only.

### IV. Single Source of Truth
- `account_config` is the **only** source for niche, keywords, voice, taboos, and the cost cap.
- Prompts are **versioned** (`prompts/<name>-vN.md`); pin in code, bump on change, store
  `prompt_version` with every AI output. Never edit a live prompt silently.

### V. Cost Discipline
A **hard monthly AI-spend cap** (`account_config.monthly_cost_cap_usd`) is enforced: alert at 80%,
throttle non-essential AI at 100% while keeping data capture + anomaly radar running.

### VI. Verification by Dry-Run (explicit decision)
Automated unit tests are **not mandated**. Each user story is validated via its **Independent Test**
(a manual dry-run) plus the plan's **Testing & Validation Checklist**. *(If this principle should
become Test-First instead, amend here before implementation begins.)*

### VII. Single-Account First, Multi-Account-Ready
Build for **one owner/account** now; all tables are keyed by `ig_user_id` and RLS-protected so a
future multi-tenant/public version is mostly a policy change.

## Quality Gates
- No user story is "done" until its Independent Test passes and a clean `pipeline_runs` row is logged.
- Publishing to the live Instagram account is always gated by a **human Approve/Edit/Skip** action.
- Regressions in `engagement_rate` self-check (>10% divergence) block the AI report.

## Governance
- This constitution supersedes conflicting detail in spec/plan/tasks; conflicts require an explicit
  amendment here first.
- Amendments require a documented change + migration note for affected artifacts.

**Version**: 0.1 (draft) · **Ratified**: _(not yet)_ · **Last Amended**: 2026-06-30
