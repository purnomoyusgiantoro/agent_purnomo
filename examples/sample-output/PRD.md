# Product Requirements Document (PRD) — TaskLite API & CLI

## 1. Executive Summary
- **Product Objective:** Lightweight local task management REST API and CLI with persistent SQLite storage for solo developers.
- **Target Users:** Terminal-first developers managing daily engineering tasks offline.
- **Recommended Minimal Tech Stack:** Python 3.11+, FastAPI, SQLite (`sqlite3`), Typer CLI, Pytest.
- **MVP Milestone Priorities:** M1 (SQLite Schema & Repository) -> M2 (REST Endpoints & Validation) -> M3 (CLI Client & Tests).

## 2. High-Level System Architecture
- `app/db.py`: SQLite connection factory and idempotent schema initialization.
- `app/main.py`: FastAPI application with CRUD routes and structured error responses.
- `app/cli.py`: Typer CLI consuming `app/db.py` directly for zero-latency local commands.

## 3. Modules & Functional Requirements
### Module 1: Task Management
- **User Story:** As a developer, I want to create, list, complete, and delete tasks via HTTP or CLI so my backlog stays synchronized.
- **Functional Requirements:**
  1. Create task with non-empty `title` (1–120 chars) and optional `priority` (`low|medium|high`, default `medium`).
  2. Filter task list by `status` (`pending|done`).
  3. Mark task as `done` idempotently.
- **Edge Cases & Error Handling:** Reject blank titles with HTTP `422`; return HTTP `404` for unknown task IDs.

## 4. Data Models & Database Schema
- Table `tasks`:
  - `id` `INTEGER PRIMARY KEY AUTOINCREMENT`
  - `title` `TEXT NOT NULL CHECK(length(trim(title)) > 0)`
  - `priority` `TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low','medium','high'))`
  - `status` `TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done'))`
  - `created_at` `TEXT NOT NULL`

## 5. API Contracts / State Transitions
- `POST /tasks` -> `201 Created` `{id, title, priority, status, created_at}`
- `GET /tasks?status=pending|done` -> `200 OK` `[...]`
- `PATCH /tasks/{id}/done` -> `200 OK` `{id, status: "done", ...}` | `404 Not Found`
- `DELETE /tasks/{id}` -> `204 No Content` | `404 Not Found`

## 6. Security & Validation Requirements
- Use parameterized SQL queries exclusively (`?` placeholders) to prevent SQL injection.
- Validate all payloads via Pydantic models with explicit length and enum bounds.

## 7. Explicit Out-of-Scope Boundaries
- Multi-user authentication, cloud sync, recurring tasks, and web dashboard UI.
