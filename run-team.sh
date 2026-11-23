#!/usr/bin/env bash
set -euo pipefail

AGENT_CMD="${AGENT_CMD:-agy}"
MAX_RETRIES="${MAX_RETRIES:-3}"
RESUME_FROM="phase1"
TARGET_DIR=""
ALLOW_INCOMPLETE_TASKS=false
ENABLE_GIT=true
IDEA=""
LOG_DIR=".agent/logs"

usage() {
  cat <<'EOF'
Usage: ./run-team.sh [OPTIONS] "<project idea>"

Options:
  --target-dir <dir>         Target project directory (scaffolds .agent/ and .gitignore if missing)
  --agent <cmd>              CLI agent command to invoke (default: agy, or $AGENT_CMD)
  --max-retries <n>          Max Phase 3-4 iterations (default: 3)
  --resume-from <phase>      Start from: phase1 | phase2 | phase3 | phase4 (default: phase1)
  --allow-incomplete-tasks   Accept STATUS: PASS even if unchecked '- [ ]' remain in TASKS.md
  --no-git                   Disable automatic Git init and phase checkpoint commits
  -h, --help                 Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-dir)
      TARGET_DIR="${2:?Missing value for --target-dir}"
      shift 2
      ;;
    --agent)
      AGENT_CMD="${2:?Missing value for --agent}"
      shift 2
      ;;
    --max-retries)
      MAX_RETRIES="${2:?Missing value for --max-retries}"
      shift 2
      ;;
    --resume-from)
      RESUME_FROM="${2:?Missing value for --resume-from}"
      shift 2
      ;;
    --allow-incomplete-tasks)
      ALLOW_INCOMPLETE_TASKS=true
      shift
      ;;
    --no-git)
      ENABLE_GIT=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      IDEA="$*"
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
    *)
      if [[ -z "$IDEA" ]]; then
        IDEA="$1"
      else
        IDEA="$IDEA $1"
      fi
      shift
      ;;
  esac
done

case "$RESUME_FROM" in
  phase1|phase2|phase3|phase4) ;;
  *)
    echo "Invalid --resume-from value: $RESUME_FROM (expected phase1|phase2|phase3|phase4)" >&2
    exit 1
    ;;
esac

if [[ "$RESUME_FROM" == "phase1" && -z "$IDEA" ]]; then
  echo "Error: Project idea is required when starting from phase1." >&2
  usage
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ensure_gitignore() {
  local gi=".gitignore"
  touch "$gi"
  local entries=(
    ".agent/logs/"
    ".env"
    ".env.*"
    "!.env.example"
    "node_modules/"
    "__pycache__/"
    "*.py[cod]"
    ".venv/"
    "venv/"
    "dist/"
    "build/"
    ".pytest_cache/"
    "coverage/"
    "*.db"
    "*.sqlite"
    "*.sqlite3"
  )
  for entry in "${entries[@]}"; do
    if ! grep -qxF "$entry" "$gi"; then
      printf '%s\n' "$entry" >> "$gi"
    fi
  done
}

if [[ -n "$TARGET_DIR" ]]; then
  TEMPLATE_ROOT="$PWD"
  if [[ ! -d "$TEMPLATE_ROOT/.agent/roles" && -d "$SCRIPT_DIR/.agent/roles" ]]; then
    TEMPLATE_ROOT="$SCRIPT_DIR"
  fi
  mkdir -p "$TARGET_DIR/.agent/roles" "$TARGET_DIR/.agent/workflows"
  if [[ -d "$TEMPLATE_ROOT/.agent/roles" ]]; then
    cp -rn "$TEMPLATE_ROOT/.agent/roles/." "$TARGET_DIR/.agent/roles/" 2>/dev/null || \
      cp -r "$TEMPLATE_ROOT/.agent/roles/." "$TARGET_DIR/.agent/roles/"
  fi
  if [[ -d "$TEMPLATE_ROOT/.agent/workflows" ]]; then
    cp -rn "$TEMPLATE_ROOT/.agent/workflows/." "$TARGET_DIR/.agent/workflows/" 2>/dev/null || \
      cp -r "$TEMPLATE_ROOT/.agent/workflows/." "$TARGET_DIR/.agent/workflows/"
  fi
  if [[ -f "$TEMPLATE_ROOT/.gitignore" && ! -f "$TARGET_DIR/.gitignore" ]]; then
    cp "$TEMPLATE_ROOT/.gitignore" "$TARGET_DIR/.gitignore"
  fi
  cd "$TARGET_DIR"
  ensure_gitignore
fi

for req in .agent/roles/pm.md .agent/roles/uiux.md .agent/roles/programmer.md .agent/roles/qc.md; do
  if [[ ! -s "$req" ]]; then
    echo "FATAL: Missing or empty role file: $req" >&2
    exit 1
  fi
done

if ! command -v "$AGENT_CMD" >/dev/null 2>&1; then
  echo "FATAL: CLI command '$AGENT_CMD' not found in PATH." >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

require_non_empty() {
  local phase_name="$1"
  shift
  for f in "$@"; do
    if [[ ! -s "$f" ]]; then
      echo "FATAL: Gate failed after $phase_name — '$f' is missing or empty." >&2
      exit 1
    fi
  done
}

git_checkpoint() {
  local msg="$1"
  if [[ "$ENABLE_GIT" != true ]] || ! command -v git >/dev/null 2>&1; then
    return 0
  fi
  ensure_gitignore
  if [[ ! -d .git ]]; then
    git init -q
  fi
  git add -A
  if ! git diff --cached --quiet; then
    git -c user.name="${GIT_AUTHOR_NAME:-agent-purnomo}" \
        -c user.email="${GIT_AUTHOR_EMAIL:-agent-purnomo@local}" \
        commit -q -m "checkpoint: $msg" || true
  fi
}

is_qa_pass() {
  [[ -s QA_REPORT.md ]] || return 1
  awk 'NF{line=$0} END{gsub(/\r/,"",line); gsub(/^[ \t]+|[ \t]+$/,"",line); exit !(line=="STATUS: PASS")}' QA_REPORT.md
}

count_unchecked_tasks() {
  if [[ ! -s TASKS.md ]]; then
    echo 0
    return 0
  fi
  grep -cE '^[[:space:]]*-[[:space:]]*\[[[:space:]]\]' TASKS.md || true
}

count_total_criteria() {
  if [[ ! -s TASKS.md ]]; then
    echo 0
    return 0
  fi
  grep -cE '^[[:space:]]*-[[:space:]]*\[[ xX]\]' TASKS.md || true
}

freeze_specs() {
  cp PRD.md "$LOG_DIR/PRD.frozen.md"
  cp DESIGN_SPEC.md "$LOG_DIR/DESIGN_SPEC.frozen.md"
  cp TASKS.md "$LOG_DIR/TASKS.frozen.md"
  FROZEN_CRITERIA_COUNT="$(count_total_criteria)"
}

enforce_spec_integrity() {
  if ! cmp -s PRD.md "$LOG_DIR/PRD.frozen.md" 2>/dev/null; then
    echo "=== [SECURITY/INTEGRITY WARN] Restoring tampered PRD.md to frozen Phase-1 snapshot ==="
    cp "$LOG_DIR/PRD.frozen.md" PRD.md
  fi
  if ! cmp -s DESIGN_SPEC.md "$LOG_DIR/DESIGN_SPEC.frozen.md" 2>/dev/null; then
    echo "=== [SECURITY/INTEGRITY WARN] Restoring tampered DESIGN_SPEC.md to frozen Phase-2 snapshot ==="
    cp "$LOG_DIR/DESIGN_SPEC.frozen.md" DESIGN_SPEC.md
  fi
  local cur_count
  cur_count="$(count_total_criteria)"
  if [[ "$cur_count" -lt "$FROZEN_CRITERIA_COUNT" ]]; then
    echo "=== [SECURITY/INTEGRITY WARN] Criteria count dropped ($cur_count < $FROZEN_CRITERIA_COUNT) in TASKS.md! Restoring frozen TASKS.md ==="
    cp "$LOG_DIR/TASKS.frozen.md" TASKS.md
  fi
}

build_programmer_prompt() {
  local iter="$1"
  local base_prompt
  base_prompt="$(cat .agent/roles/programmer.md)

Read ./PRD.md, ./TASKS.md, ./DESIGN_SPEC.md, and ./QA_REPORT.md (if present). Implement pending tasks or fix logged bugs, update verified checkboxes in ./TASKS.md, and verify build/typecheck in terminal."

  if [[ "$iter" -le 1 && ! -f QA_REPORT.md ]]; then
    printf '%s' "$base_prompt"
    return 0
  fi

  local unchecked_list=""
  if [[ -s TASKS.md ]]; then
    unchecked_list="$(grep -E '^[[:space:]]*-[[:space:]]*\[[[:space:]]\]' TASKS.md | head -n 25 || true)"
  fi

  local bug_list=""
  if [[ -s QA_REPORT.md ]]; then
    bug_list="$(grep -E '(^### BUG-|CRITICAL|MAJOR)' QA_REPORT.md | head -n 25 || true)"
  fi

  printf '%s' "$base_prompt"
  if [[ -n "$bug_list" || -n "$unchecked_list" ]]; then
    printf '\n\n=== FOCUSED RETRY CONTEXT (ITERATION %s) ===\n' "$iter"
    if [[ -n "$bug_list" ]]; then
      printf 'ACTIVE QA DEFECTS TO FIX FIRST:\n%s\n\n' "$bug_list"
    fi
    if [[ -n "$unchecked_list" ]]; then
      printf 'REMAINING UNCHECKED TASKS:\n%s\n' "$unchecked_list"
    fi
  fi
}

run_agent() {
  local log_file="$1"
  local prompt_text="$2"
  "$AGENT_CMD" -p "$prompt_text" 2>&1 | tee "$log_file"
  local rc="${PIPESTATUS[0]}"
  if [[ "$rc" -ne 0 ]]; then
    return "$rc"
  fi
  if grep -qE '(insufficient_quota|invalid_api_key|exceeded your current quota|^(Error|FATAL|Exception):[[:space:]]*(RateLimitError|AuthenticationError|QuotaExceeded))' "$log_file"; then
    echo "FATAL: Detected silent fatal CLI/API error in $log_file" >&2
    return 1
  fi
  return 0
}

if [[ "$RESUME_FROM" == "phase1" ]]; then
  echo "=== [PHASE 1] Project Manager -> PRD.md & TASKS.md ==="
  PM_PROMPT="$(cat .agent/roles/pm.md)

USER REQUEST:
$IDEA"
  run_agent "$LOG_DIR/phase1.log" "$PM_PROMPT"
  require_non_empty "Phase 1" PRD.md TASKS.md
  git_checkpoint "phase-1-prd-and-tasks"
fi

if [[ "$RESUME_FROM" == "phase1" || "$RESUME_FROM" == "phase2" ]]; then
  require_non_empty "Phase 2 precondition" PRD.md TASKS.md
  echo "=== [PHASE 2] UI/UX Designer -> DESIGN_SPEC.md ==="
  UIUX_PROMPT="$(cat .agent/roles/uiux.md)

Read ./PRD.md and ./TASKS.md from the current directory and generate ./DESIGN_SPEC.md."
  run_agent "$LOG_DIR/phase2.log" "$UIUX_PROMPT"
  require_non_empty "Phase 2" DESIGN_SPEC.md
  git_checkpoint "phase-2-design-spec"
fi

require_non_empty "Phase 3 precondition" PRD.md TASKS.md DESIGN_SPEC.md
freeze_specs

for i in $(seq 1 "$MAX_RETRIES"); do
  if [[ "$i" -eq 1 && "$RESUME_FROM" == "phase4" ]]; then
    echo "=== [SKIP] Resuming directly at Phase 4 (Iteration $i/$MAX_RETRIES) ==="
  else
    echo "=== [PHASE 3 - Iteration $i/$MAX_RETRIES] Programmer -> Implementation & Build ==="
    PROG_PROMPT="$(build_programmer_prompt "$i")"
    run_agent "$LOG_DIR/phase3_iter${i}.log" "$PROG_PROMPT"
    enforce_spec_integrity
    git_checkpoint "phase-3-iter-${i}"
  fi

  # Archive stale QA_REPORT.md before Phase 4 so previous verdicts cannot leak
  if [[ -f QA_REPORT.md ]]; then
    mv QA_REPORT.md "$LOG_DIR/QA_REPORT.before-iter${i}.md"
  fi

  echo "=== [PHASE 4 - Iteration $i/$MAX_RETRIES] QC Tester -> Automated Test & Audit ==="
  QC_PROMPT="$(cat .agent/roles/qc.md)

Read ./PRD.md, ./TASKS.md, and ./DESIGN_SPEC.md. Write and run automated tests safely in terminal (no hanging servers or leaked ports), then write a fresh ./QA_REPORT.md ending with STATUS: PASS or STATUS: FAIL."
  run_agent "$LOG_DIR/phase4_iter${i}.log" "$QC_PROMPT"
  require_non_empty "Phase 4 (Iteration $i)" QA_REPORT.md

  QA_OK=false
  if is_qa_pass; then
    UNCHECKED_COUNT="$(count_unchecked_tasks)"
    if [[ "$UNCHECKED_COUNT" -eq 0 || "$ALLOW_INCOMPLETE_TASKS" == true ]]; then
      QA_OK=true
    else
      echo "=== [WARN] QA_REPORT.md returned STATUS: PASS, but $UNCHECKED_COUNT unchecked item(s) remain in TASKS.md! ==="
      printf '\n\n## Backlog Completion Gate Failure\n- **Severity:** `MAJOR`\n- **Detail:** %s unchecked acceptance criteria remain in `./TASKS.md`.\n\nSTATUS: FAIL\n' "$UNCHECKED_COUNT" >> QA_REPORT.md
    fi
  fi

  cp QA_REPORT.md "$LOG_DIR/QA_REPORT.iter${i}.md"
  git_checkpoint "phase-4-iter-${i}"

  if [[ "$QA_OK" == true ]]; then
    echo "=== [SUCCESS] Passed QC, Spec Integrity, and Backlog Gate on iteration $i! ==="
    exit 0
  fi

  echo "=== [FAIL] Defects or unfinished tasks remain on iteration $i. Routing back to Programmer... ==="
done

echo "=== [STOP] Reached max retries ($MAX_RETRIES). Inspect QA_REPORT.md and $LOG_DIR/ for remaining defects. ==="
exit 1
