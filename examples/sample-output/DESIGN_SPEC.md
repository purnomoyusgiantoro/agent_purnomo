# Interface & Design System Specification — TaskLite CLI

## 1. Design System Summary
- **Aesthetic Direction:** Minimalist high-contrast terminal UI with crisp tabular columns and semantic ANSI color cues.
- **Color Palette (Exact Hex / Terminal Mapping):**
  - Background: `#0F172A`
  - Surface / Card: `#1E293B`
  - Border: `#334155`
  - Text Primary / Muted: `#F8FAFC` / `#94A3B8`
  - Primary / Hover: `#38BDF8` / `#0EA5E9`
  - Secondary: `#818CF8`
  - Semantic (Success / Warning / Error): `#22C55E` / `#F59E0B` / `#EF4444`
- **Typography Scale:** Monospace `JetBrains Mono` / system monospace, 14px base, 1.5 line height.
- **Spacing, Border Radii & Elevation:** 8px grid (`4px`, `8px`, `16px`), flat bordered surfaces (`1px solid #334155`), instant 120ms status transitions.

## 2. Screen Inventory & Layouts
### Screen 1: Terminal Task Table (`tasklite list`)
- **Visual Hierarchy & Primary Focal Point:** Pending high-priority tasks sorted at the top.
- **Layout Grid & Responsive Breakpoints:** Desktop (`>=100 cols` full table), Narrow/Mobile (`<80 cols` stacked compact lines).
- **Structural ASCII Wireframe:**
  ```text
  +----+------------------------+----------+---------+
  | ID | Title                  | Priority | Status  |
  +----+------------------------+----------+---------+
  |  1 | Write FastAPI CRUD     | high     | pending |
  |  2 | Add pytest fixtures    | medium   | done    |
  +----+------------------------+----------+---------+
  ```
- **Four Required Data States:**
  - **Default:** Formatted ASCII/Rich table with status badges.
  - **Loading:** Spinner (`Fetching tasks...`) on operations >200ms.
  - **Empty:** `No tasks found. Run 'tasklite add "Your first task"' to get started.`
  - **Error:** Red stderr banner (`Error: Database unreachable at <path>. Verify TASKLITE_DB_PATH.`) and exit code `1`.

## 3. Component Inventory & States
- CLI Commands (`add`, `list`, `done`, `delete`) with `--json` machine-readable flag and deterministic exit codes (`0` success, `1` runtime error, `2` validation error).

## 4. WCAG Accessibility Rules
- Color is never the sole status indicator (`pending` / `done` text labels always accompany ANSI colors). Contrast ratio >= 4.5:1 on dark slate surfaces.

## 5. Component-to-Task Mapping
| Component / Screen | Target File(s) | Mapped Task ID(s) |
| :--- | :--- | :--- |
| CLI Table & States | `app/cli.py` | `TASK-03` |
| API Error Payloads | `app/main.py` | `TASK-02` |
