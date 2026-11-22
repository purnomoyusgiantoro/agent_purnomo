#!/usr/bin/env python3
"""Cross-platform orchestrator for the 4-agent terminal coding team pipeline."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

LOG_DIR = Path(".agent/logs")
ROLE_FILES = {
    "pm": Path(".agent/roles/pm.md"),
    "uiux": Path(".agent/roles/uiux.md"),
    "programmer": Path(".agent/roles/programmer.md"),
    "qc": Path(".agent/roles/qc.md"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the autonomous 4-agent coding team pipeline (PM -> UI/UX -> Programmer -> QC)."
    )
    parser.add_argument(
        "idea",
        nargs="?",
        default="",
        help="Project idea or specification (optional if --idea or --resume-from phase2+ is used).",
    )
    parser.add_argument(
        "--idea",
        dest="idea_flag",
        default="",
        help="Project idea or specification (alternative to positional argument).",
    )
    parser.add_argument(
        "--agent",
        default=os.environ.get("AGENT_CMD", "agy"),
        help="CLI agent binary to execute (default: agy or $AGENT_CMD).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum Phase 3-4 iterations (default: 3).",
    )
    parser.add_argument(
        "--resume-from",
        choices=["phase1", "phase2", "phase3", "phase4"],
        default="phase1",
        help="Resume execution from a specific phase (default: phase1).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Timeout in seconds per phase invocation (default: 1800).",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Disable automatic Git initialization and phase checkpoint commits.",
    )
    args = parser.parse_args()
    args.resolved_idea = (args.idea_flag or args.idea).strip()
    if args.max_retries < 1:
        parser.error("--max-retries must be >= 1")
    if args.resume_from == "phase1" and not args.resolved_idea:
        parser.error("A project idea is required when starting from phase1.")
    return args


def ensure_prerequisites(agent_cmd: str) -> None:
    for role_name, path in ROLE_FILES.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"FATAL: Missing or empty role file for '{role_name}': {path}")
    if shutil.which(agent_cmd) is None:
        raise SystemExit(f"FATAL: CLI command '{agent_cmd}' not found in PATH.")
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def validate_artifact(path: Path, phase_name: str, required_pattern: str | None = None) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"FATAL: Gate failed after {phase_name} — '{path}' is missing or empty.")
    if required_pattern:
        content = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(required_pattern, content, flags=re.MULTILINE):
            raise SystemExit(
                f"FATAL: Schema gate failed after {phase_name} — '{path}' missing expected pattern: {required_pattern}"
            )


def git_checkpoint(message: str, enabled: bool) -> None:
    if not enabled or shutil.which("git") is None:
        return
    if not Path(".git").exists():
        subprocess.run(["git", "init", "-q"], check=False)
    subprocess.run(["git", "add", "-A"], check=False)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        return
    author_name = os.environ.get("GIT_AUTHOR_NAME", "agent-purnomo")
    author_email = os.environ.get("GIT_AUTHOR_EMAIL", "agent-purnomo@local")
    subprocess.run(
        [
            "git",
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "-q",
            "-m",
            f"checkpoint: {message}",
        ],
        check=False,
    )


def run_agent(agent_cmd: str, prompt: str, log_path: Path, timeout_sec: int) -> None:
    cmd = [agent_cmd, "-p", prompt]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise SystemExit(f"FATAL: Failed to launch '{agent_cmd}': {exc}") from exc

    collected: list[str] = []
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            collected.append(line)
        rc = proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.wait()
        log_path.write_text("".join(collected), encoding="utf-8")
        raise SystemExit(f"FATAL: Phase timed out after {timeout_sec}s. Partial log: {log_path}") from exc

    log_path.write_text("".join(collected), encoding="utf-8")
    if rc != 0:
        raise SystemExit(f"FATAL: '{agent_cmd}' exited with status {rc}. See {log_path}")


def is_qa_pass(qa_path: Path) -> bool:
    if not qa_path.is_file() or qa_path.stat().st_size == 0:
        return False
    lines = [ln.strip() for ln in qa_path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    if not lines:
        return False
    return lines[-1] == "STATUS: PASS"


def print_summary(passed: bool, iterations_run: int) -> None:
    print("\n=== [RELEASE SUMMARY] ===")
    print(f"Final Verdict : {'PASS' if passed else 'FAIL'}")
    print(f"Iterations Run: {iterations_run}")
    for artifact in ("PRD.md", "TASKS.md", "DESIGN_SPEC.md", "QA_REPORT.md"):
        p = Path(artifact)
        status = f"{p.stat().st_size} bytes" if p.is_file() else "MISSING"
        print(f"  - {artifact}: {status}")
    print(f"Logs Directory: {LOG_DIR}")


def main() -> int:
    args = parse_args()
    ensure_prerequisites(args.agent)
    enable_git = not args.no_git

    if args.resume_from == "phase1":
        print("=== [PHASE 1] Project Manager -> PRD.md & TASKS.md ===")
        pm_prompt = f"{ROLE_FILES['pm'].read_text(encoding='utf-8')}\n\nUSER REQUEST:\n{args.resolved_idea}"
        run_agent(args.agent, pm_prompt, LOG_DIR / "phase1.log", args.timeout)
        validate_artifact(Path("PRD.md"), "Phase 1", r"^#\s+")
        validate_artifact(Path("TASKS.md"), "Phase 1", r"TASK-\d+")
        git_checkpoint("phase-1-prd-and-tasks", enable_git)

    if args.resume_from in ("phase1", "phase2"):
        validate_artifact(Path("PRD.md"), "Phase 2 precondition")
        validate_artifact(Path("TASKS.md"), "Phase 2 precondition")
        print("=== [PHASE 2] UI/UX Designer -> DESIGN_SPEC.md ===")
        uiux_prompt = (
            f"{ROLE_FILES['uiux'].read_text(encoding='utf-8')}\n\n"
            "Read ./PRD.md and ./TASKS.md from the current directory and generate ./DESIGN_SPEC.md."
        )
        run_agent(args.agent, uiux_prompt, LOG_DIR / "phase2.log", args.timeout)
        validate_artifact(Path("DESIGN_SPEC.md"), "Phase 2", r"^#\s+")
        git_checkpoint("phase-2-design-spec", enable_git)

    validate_artifact(Path("PRD.md"), "Phase 3 precondition")
    validate_artifact(Path("TASKS.md"), "Phase 3 precondition")
    validate_artifact(Path("DESIGN_SPEC.md"), "Phase 3 precondition")

    qa_path = Path("QA_REPORT.md")
    iterations_run = 0

    for i in range(1, args.max_retries + 1):
        iterations_run = i
        if i == 1 and args.resume_from == "phase4":
            print(f"=== [SKIP] Resuming directly at Phase 4 (Iteration {i}/{args.max_retries}) ===")
        else:
            print(f"=== [PHASE 3 - Iteration {i}/{args.max_retries}] Programmer -> Implementation & Build ===")
            prog_prompt = (
                f"{ROLE_FILES['programmer'].read_text(encoding='utf-8')}\n\n"
                "Read ./PRD.md, ./TASKS.md, ./DESIGN_SPEC.md, and ./QA_REPORT.md (if present). "
                "Implement pending tasks or fix logged bugs, update verified checkboxes in ./TASKS.md, "
                "and verify build/typecheck in terminal."
            )
            run_agent(args.agent, prog_prompt, LOG_DIR / f"phase3_iter{i}.log", args.timeout)
            git_checkpoint(f"phase-3-iter-{i}", enable_git)

        # Archive stale QA_REPORT.md before Phase 4 so previous verdicts cannot leak
        if qa_path.exists():
            shutil.move(str(qa_path), str(LOG_DIR / f"QA_REPORT.before-iter{i}.md"))

        print(f"=== [PHASE 4 - Iteration {i}/{args.max_retries}] QC Tester -> Automated Test & Audit ===")
        qc_prompt = (
            f"{ROLE_FILES['qc'].read_text(encoding='utf-8')}\n\n"
            "Read ./PRD.md, ./TASKS.md, and ./DESIGN_SPEC.md. "
            "Write and run automated tests safely in terminal (no hanging servers or leaked ports), "
            "then write a fresh ./QA_REPORT.md ending with STATUS: PASS or STATUS: FAIL."
        )
        run_agent(args.agent, qc_prompt, LOG_DIR / f"phase4_iter{i}.log", args.timeout)
        validate_artifact(qa_path, f"Phase 4 (Iteration {i})", r"^STATUS:\s*(PASS|FAIL)\s*$")
        shutil.copy2(qa_path, LOG_DIR / f"QA_REPORT.iter{i}.md")
        git_checkpoint(f"phase-4-iter-{i}", enable_git)

        if is_qa_pass(qa_path):
            print(f"=== [SUCCESS] Passed QC on iteration {i}! ===")
            print_summary(True, iterations_run)
            return 0

        print(f"=== [FAIL] Defects logged in QA_REPORT.md on iteration {i}. Routing back to Programmer... ===")

    print(f"=== [STOP] Reached max retries ({args.max_retries}). Inspect QA_REPORT.md and {LOG_DIR}/ ===")
    print_summary(False, iterations_run)
    return 1


if __name__ == "__main__":
    sys.exit(main())
