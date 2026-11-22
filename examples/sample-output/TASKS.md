# Engineering Backlog — TaskLite

## Milestone 1: Scaffolding & Core Data Layer
### TASK-01: Project Scaffolding & SQLite Repository
- **Milestone:** M1
- **Dependencies:** None
- **Target Files:** `.env.example`, `requirements.txt`, `app/db.py`
- **Implementation Notes:** Configure `TASKLITE_DB_PATH` via `.env.example` (default `./tasklite.db`). Use parameterized SQLite queries and WAL mode.
- **Acceptance Criteria:**
  - [x] `app/db.py` initializes the `tasks` table idempotently on startup
  - [x] Blank titles and invalid priorities are rejected at both app and DB constraint layers

## Milestone 2: Core Business Logic & API
### TASK-02: FastAPI CRUD Endpoints & Validation
- **Milestone:** M2
- **Dependencies:** TASK-01
- **Target Files:** `app/schemas.py`, `app/main.py`
- **Implementation Notes:** Implement `POST /tasks`, `GET /tasks`, `PATCH /tasks/{id}/done`, and `DELETE /tasks/{id}` with Pydantic validation.
- **Acceptance Criteria:**
  - [x] `POST /tasks` returns HTTP `201` for valid payloads and `422` for blank titles
  - [x] `PATCH /tasks/{id}/done` and `DELETE /tasks/{id}` return `404` for nonexistent IDs

## Milestone 3: CLI Client & Automated Test Suite
### TASK-03: CLI Interface & Pytest Integration Suite
- **Milestone:** M3
- **Dependencies:** TASK-02
- **Target Files:** `app/cli.py`, `tests/test_api.py`
- **Implementation Notes:** Test API endpoints using FastAPI `TestClient` with an isolated temporary SQLite file per test run.
- **Acceptance Criteria:**
  - [x] `pytest` runs cleanly without leaving temp DB files or background processes
  - [x] All happy-path and error-path assertions pass with exit code `0`
