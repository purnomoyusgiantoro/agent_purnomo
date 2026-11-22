#!/usr/bin/env bash
set -euo pipefail

AGENT_CMD="${AGENT_CMD:-agy}"
MAX_RETRIES="${MAX_RETRIES:-3}"
RESUME_FROM="phase1"
ENABLE_GIT=true
IDEA=""
LOG_DIR=".agent/logs"

usage() {
  cat <<'EOF'
Usage: ./run-team.sh [OPTIONS] "<project idea>"

Options:
  --agent <cmd>          CLI agent command to invoke (default: agy, or $AGENT_CMD)
  --max-retries <n>      Max Phase 3-4 iterations (default: 3)
  --resume-from <phase>  Start from: phase1 | phase2 | phase3 | phase4 (default: phase1)
  --no-git               Disable automatic Git init and phase checkpoint commits
  -h, --help             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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

run_agent() {
  local log_file="$1"
  local prompt_text="$2"
  "$AGENT_CMD" -p "$prompt_text" 2>&1 | tee "$log_file"
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

for i in $(seq 1 "$MAX_RETRIES"); do
  if [[ "$i" -eq 1 && "$RESUME_FROM" == "phase4" ]]; then
    echo "=== [SKIP] Resuming directly at Phase 4 (Iteration $i/$MAX_RETRIES) ==="
  else
    echo "=== [PHASE 3 - Iteration $i/$MAX_RETRIES] Programmer -> Implementation & Build ==="
    PROG_PROMPT="$(cat .agent/roles/programmer.md)

Read ./PRD.md, ./TASKS.md, ./DESIGN_SPEC.md, and ./QA_REPORT.md (if present). Implement pending tasks or fix logged bugs, update verified checkboxes in ./TASKS.md, and verify build/typecheck in terminal."
    run_agent "$LOG_DIR/phase3_iter${i}.log" "$PROG_PROMPT"
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
  cp QA_REPORT.md "$LOG_DIR/QA_REPORT.iter${i}.md"
  git_checkpoint "phase-4-iter-${i}"

  if is_qa_pass; then
    echo "=== [SUCCESS] Passed QC on iteration $i! ==="
    exit 0
  fi

  echo "=== [FAIL] Defects logged in QA_REPORT.md on iteration $i. Routing back to Programmer... ==="
done

echo "=== [STOP] Reached max retries ($MAX_RETRIES). Inspect QA_REPORT.md and $LOG_DIR/ for remaining defects. ==="
exit 1
