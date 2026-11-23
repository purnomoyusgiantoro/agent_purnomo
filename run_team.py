#!/usr/bin/env python3
"""Cross-platform orchestrator for the 4-agent terminal coding team pipeline."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

LOG_DIR = Path(".agent/logs")
ROLE_FILES = {
    "pm": Path(".agent/roles/pm.md"),
    "uiux": Path(".agent/roles/uiux.md"),
    "programmer": Path(".agent/roles/programmer.md"),
    "qc": Path(".agent/roles/qc.md"),
}

DEFAULT_GITIGNORE_ENTRIES = [
    ".agent/logs/",
    ".env",
    ".env.*",
    "!.env.example",
    "node_modules/",
    "__pycache__/",
    "*.py[cod]",
    ".venv/",
    "venv/",
    "dist/",
    "build/",
    ".pytest_cache/",
    "coverage/",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    ".DS_Store",
    "Thumbs.db",
]

AGENT_ADAPTERS: dict[str, dict[str, object]] = {
    "agy": {"extra_args": [], "prompt_flag": "-p"},
    "gemini": {"extra_args": [], "prompt_flag": "-p"},
    "claude": {"extra_args": ["--dangerously-skip-permissions"], "prompt_flag": "-p"},
    "codex": {"extra_args": ["--full-auto"], "prompt_flag": ""},
}

SENSITIVE_ENV_EXACT = {
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITLAB_TOKEN",
    "NPM_TOKEN",
    "PYPI_TOKEN",
    "DOCKER_PASSWORD",
    "SSH_AUTH_SOCK",
}
SENSITIVE_ENV_PREFIXES = ("AWS_", "AZURE_", "GCP_SERVICE_ACCOUNT")

FATAL_LOG_PATTERNS = [
    re.compile(
        r"^\s*(?:Error|FATAL|Exception):\s*(?:RateLimitError|AuthenticationError|QuotaExceeded|ContextWindowExceededError)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"\b(?:insufficient_quota|invalid_api_key|exceeded your current quota|APIError:\s*(?:401|403|429|500|502|503))\b",
        re.IGNORECASE,
    ),
]

WINDOWS_ARG_CHAR_LIMIT = 8000


@dataclass(frozen=True)
class SpecSnapshot:
    prd_bytes: bytes
    prd_sha256: str
    design_bytes: bytes | None
    design_sha256: str | None
    tasks_criteria: tuple[tuple[str, str], ...]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
        "--target-dir",
        default="",
        help="Target project workspace directory. Scaffolds .agent/ and .gitignore automatically if missing.",
    )
    parser.add_argument(
        "--agent",
        default=os.environ.get("AGENT_CMD", "agy"),
        help="CLI agent binary to execute (default: agy or $AGENT_CMD).",
    )
    parser.add_argument(
        "--agent-args",
        default="",
        help="Additional CLI arguments passed to the agent command (quoted string).",
    )
    parser.add_argument(
        "--prompt-mode",
        choices=["auto", "arg", "stdin"],
        default="auto",
        help="How prompts are delivered to the CLI agent (default: auto; switches to stdin on long Windows prompts).",
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
        "--allow-incomplete-tasks",
        action="store_true",
        help="Allow STATUS: PASS even if unchecked '- [ ]' items remain in TASKS.md.",
    )
    parser.add_argument(
        "--strict-sandbox",
        action="store_true",
        help="Strip unrelated host credential env vars (GITHUB_TOKEN, AWS_*, etc.) from child agent processes.",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Disable automatic Git initialization and phase checkpoint commits.",
    )
    args = parser.parse_args(argv)
    args.resolved_idea = (args.idea_flag or args.idea).strip()
    if args.max_retries < 1:
        parser.error("--max-retries must be >= 1")
    if args.timeout < 1:
        parser.error("--timeout must be >= 1")
    if args.resume_from == "phase1" and not args.resolved_idea:
        parser.error("A project idea is required when starting from phase1.")
    return args


def resolve_template_root() -> Path:
    """Locate the directory containing .agent/roles templates."""
    cwd_roles = Path.cwd() / ".agent" / "roles"
    if cwd_roles.is_dir():
        return Path.cwd()
    script_roles = Path(__file__).resolve().parent / ".agent" / "roles"
    if script_roles.is_dir():
        return Path(__file__).resolve().parent
    return Path.cwd()


def bootstrap_target_dir(target_dir: Path, template_root: Path) -> None:
    """Create target_dir and copy missing .agent roles/workflows and .gitignore from template_root."""
    target_dir.mkdir(parents=True, exist_ok=True)
    src_agent = template_root / ".agent"
    dst_agent = target_dir / ".agent"

    for subdir in ("roles", "workflows"):
        src_sub = src_agent / subdir
        if src_sub.is_dir():
            dst_sub = dst_agent / subdir
            dst_sub.mkdir(parents=True, exist_ok=True)
            for item in src_sub.iterdir():
                if item.is_file():
                    dst_item = dst_sub / item.name
                    if not dst_item.exists():
                        shutil.copy2(item, dst_item)

    src_gitignore = template_root / ".gitignore"
    dst_gitignore = target_dir / ".gitignore"
    if src_gitignore.is_file() and not dst_gitignore.exists():
        shutil.copy2(src_gitignore, dst_gitignore)
    ensure_gitignore(dst_gitignore)


def ensure_gitignore(gitignore_path: Path = Path(".gitignore")) -> None:
    """Ensure critical ignore patterns exist before running git add -A."""
    existing_text = ""
    if gitignore_path.is_file():
        existing_text = gitignore_path.read_text(encoding="utf-8", errors="replace")

    existing_entries = {
        line.strip()
        for line in existing_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing = [entry for entry in DEFAULT_GITIGNORE_ENTRIES if entry not in existing_entries]
    if not missing:
        return

    parts: list[str] = []
    if existing_text:
        parts.append(existing_text.rstrip("\n"))
        parts.append("")
    parts.append("# Added automatically by agent_purnomo safety guard")
    parts.extend(missing)
    gitignore_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def build_sanitized_env(strict_sandbox: bool = False, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build child process environment, stripping sensitive host credentials when strict_sandbox is enabled."""
    env = dict(os.environ if base_env is None else base_env)
    if not strict_sandbox:
        return env
    for key in list(env.keys()):
        upper = key.upper()
        if upper in SENSITIVE_ENV_EXACT or any(upper.startswith(prefix) for prefix in SENSITIVE_ENV_PREFIXES):
            del env[key]
    return env


def resolve_agent_executable(agent_cmd: str) -> str:
    resolved = shutil.which(agent_cmd)
    if resolved is not None:
        return resolved
    candidate = Path(agent_cmd)
    if candidate.is_file():
        return str(candidate)
    raise SystemExit(f"FATAL: CLI command '{agent_cmd}' not found in PATH.")


def ensure_prerequisites(agent_cmd: str) -> str:
    for role_name, path in ROLE_FILES.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"FATAL: Missing or empty role file for '{role_name}': {path}")
    resolved_cmd = resolve_agent_executable(agent_cmd)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return resolved_cmd


def build_agent_command(
    agent_cmd: str,
    resolved_executable: str,
    prompt: str,
    prompt_mode: str = "auto",
    extra_args_str: str = "",
) -> tuple[list[str], str | None]:
    """Build CLI command list and optional stdin payload using adapter rules."""
    adapter_key = Path(agent_cmd).stem.lower()
    adapter = AGENT_ADAPTERS.get(adapter_key, {"extra_args": [], "prompt_flag": "-p"})
    adapter_args = list(adapter["extra_args"])  # type: ignore[arg-type]
    prompt_flag = str(adapter["prompt_flag"])
    user_args = shlex.split(extra_args_str) if extra_args_str.strip() else []
    merged_args = adapter_args + user_args

    effective_mode = prompt_mode
    if effective_mode == "auto":
        is_win_batch = os.name == "nt" and resolved_executable.lower().endswith((".cmd", ".bat"))
        if (os.name == "nt" and len(prompt) > WINDOWS_ARG_CHAR_LIMIT) or (is_win_batch and "\n" in prompt) or not prompt_flag:
            effective_mode = "stdin"
        else:
            effective_mode = "arg"

    cmd = [resolved_executable, *merged_args]
    if effective_mode == "stdin":
        if adapter_key == "claude" and "-p" not in merged_args:
            cmd.append("-p")
        return cmd, prompt

    if prompt_flag:
        cmd.append(prompt_flag)
    cmd.append(prompt)
    return cmd, None


def validate_artifact(path: Path, phase_name: str, required_pattern: str | None = None) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"FATAL: Gate failed after {phase_name} — '{path}' is missing or empty.")
    if required_pattern:
        content = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(required_pattern, content, flags=re.MULTILINE):
            raise SystemExit(
                f"FATAL: Schema gate failed after {phase_name} — '{path}' missing expected pattern: {required_pattern}"
            )


def extract_all_criteria(tasks_path: Path) -> list[tuple[str, str]]:
    """Return ordered list of (TASK-ID, criterion_text) across both '[ ]' and '[x]' checkboxes."""
    if not tasks_path.is_file():
        return []
    current_task = "BACKLOG"
    criteria: list[tuple[str, str]] = []
    for raw_line in tasks_path.read_text(encoding="utf-8", errors="replace").splitlines():
        task_match = re.search(r"\b(TASK-\d+)\b", raw_line)
        if raw_line.lstrip().startswith("#") and task_match:
            current_task = task_match.group(1)
            continue
        item_match = re.match(r"^\s*-\s*\[[ xX]\]\s+(.+?)\s*$", raw_line)
        if item_match:
            criteria.append((current_task, item_match.group(1)))
    return criteria


def extract_unchecked_tasks(tasks_path: Path) -> list[str]:
    """Return unchecked '- [ ] ...' criteria tagged with their parent TASK-ID."""
    if not tasks_path.is_file():
        return []
    current_task = "BACKLOG"
    unchecked: list[str] = []
    for raw_line in tasks_path.read_text(encoding="utf-8", errors="replace").splitlines():
        task_match = re.search(r"\b(TASK-\d+)\b", raw_line)
        if raw_line.lstrip().startswith("#") and task_match:
            current_task = task_match.group(1)
            continue
        item_match = re.match(r"^\s*-\s*\[\s\]\s+(.+?)\s*$", raw_line)
        if item_match:
            unchecked.append(f"[{current_task}] {item_match.group(1)}")
    return unchecked


def capture_spec_snapshot(
    prd_path: Path = Path("PRD.md"),
    design_path: Path = Path("DESIGN_SPEC.md"),
    tasks_path: Path = Path("TASKS.md"),
) -> SpecSnapshot:
    """Capture cryptographic hashes of specs and frozen acceptance criteria before Phase 3."""
    prd_bytes = prd_path.read_bytes()
    prd_sha = hashlib.sha256(prd_bytes).hexdigest()

    design_bytes: bytes | None = None
    design_sha: str | None = None
    if design_path.is_file():
        design_bytes = design_path.read_bytes()
        design_sha = hashlib.sha256(design_bytes).hexdigest()

    criteria = tuple(extract_all_criteria(tasks_path))
    return SpecSnapshot(
        prd_bytes=prd_bytes,
        prd_sha256=prd_sha,
        design_bytes=design_bytes,
        design_sha256=design_sha,
        tasks_criteria=criteria,
    )


def enforce_spec_integrity(
    snapshot: SpecSnapshot,
    prd_path: Path = Path("PRD.md"),
    design_path: Path = Path("DESIGN_SPEC.md"),
    tasks_path: Path = Path("TASKS.md"),
) -> list[str]:
    """Restore tampered specs and re-insert any deleted acceptance criteria as unchecked."""
    warnings: list[str] = []

    current_prd_sha = hashlib.sha256(prd_path.read_bytes()).hexdigest() if prd_path.is_file() else ""
    if current_prd_sha != snapshot.prd_sha256:
        prd_path.write_bytes(snapshot.prd_bytes)
        warnings.append("Restored tampered PRD.md to frozen Phase-1 snapshot.")

    if snapshot.design_bytes is not None and snapshot.design_sha256 is not None:
        current_design_sha = hashlib.sha256(design_path.read_bytes()).hexdigest() if design_path.is_file() else ""
        if current_design_sha != snapshot.design_sha256:
            design_path.write_bytes(snapshot.design_bytes)
            warnings.append("Restored tampered DESIGN_SPEC.md to frozen Phase-2 snapshot.")

    if snapshot.tasks_criteria:
        current_set = set(extract_all_criteria(tasks_path))
        missing = [pair for pair in snapshot.tasks_criteria if pair not in current_set]
        if missing:
            existing_text = tasks_path.read_text(encoding="utf-8", errors="replace").rstrip() if tasks_path.is_file() else "# Engineering Backlog"
            grouped: dict[str, list[str]] = {}
            for task_id, criterion in missing:
                grouped.setdefault(task_id, []).append(criterion)

            restored_blocks = [
                existing_text,
                "",
                "## Restored Frozen Acceptance Criteria (Anti-Tamper Guard)",
            ]
            for task_id, items in grouped.items():
                restored_blocks.append(f"### {task_id} (Restored)")
                for item in items:
                    restored_blocks.append(f"- [ ] {item}")

            tasks_path.write_text("\n".join(restored_blocks) + "\n", encoding="utf-8")
            warnings.append(f"Restored {len(missing)} deleted acceptance criteria back to TASKS.md as unchecked.")

    for w in warnings:
        print(f"=== [SECURITY/INTEGRITY WARN] {w} ===")
    return warnings


def extract_qa_defects(qa_path: Path) -> list[str]:
    """Extract defect headings or severity lines from QA_REPORT.md for focused retry prompts."""
    if not qa_path.is_file():
        return []
    lines = qa_path.read_text(encoding="utf-8", errors="replace").splitlines()
    defects: list[str] = []
    in_bug = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^###\s+BUG-\d+", stripped):
            in_bug = True
            defects.append(stripped)
        elif in_bug:
            if stripped.startswith("## ") or stripped.startswith("STATUS:"):
                in_bug = False
            elif stripped:
                defects.append(f"  {stripped}")
        elif any(sev in stripped for sev in ("CRITICAL", "MAJOR")) and not stripped.startswith("*"):
            defects.append(stripped)
    return defects[:40]


def build_programmer_prompt(
    role_text: str,
    iteration: int,
    tasks_path: Path = Path("TASKS.md"),
    qa_path: Path = Path("QA_REPORT.md"),
) -> str:
    base = (
        f"{role_text}\n\n"
        "Read ./PRD.md, ./TASKS.md, ./DESIGN_SPEC.md, and ./QA_REPORT.md (if present). "
        "Implement pending tasks or fix logged bugs, update verified checkboxes in ./TASKS.md, "
        "and verify build/typecheck in terminal."
    )
    if iteration <= 1 and not qa_path.is_file():
        return base

    context_sections: list[str] = []
    defects = extract_qa_defects(qa_path)
    if defects:
        context_sections.append("ACTIVE QA DEFECTS TO FIX FIRST:\n" + "\n".join(defects))

    unchecked = extract_unchecked_tasks(tasks_path)
    if unchecked:
        listed = "\n".join(f"- {item}" for item in unchecked[:25])
        context_sections.append(f"REMAINING UNCHECKED ACCEPTANCE CRITERIA ({len(unchecked)}):\n{listed}")

    if not context_sections:
        return base

    return base + "\n\n=== FOCUSED RETRY CONTEXT (ITERATION " + str(iteration) + ") ===\n" + "\n\n".join(context_sections)


def check_log_for_fatal_errors(log_text: str, phase_name: str, log_path: Path) -> None:
    """Detect fatal CLI/API errors even if the subprocess exited with status 0."""
    for pattern in FATAL_LOG_PATTERNS:
        match = pattern.search(log_text)
        if match:
            raise SystemExit(
                f"FATAL: Detected silent fatal CLI/API error in {phase_name} ({match.group(0).strip()}). See {log_path}"
            )


def terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Kill the child process and all orphaned descendants/servers in its process group."""
    pid = proc.pid
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            proc.kill()
        except OSError:
            pass
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass


def git_checkpoint(message: str, enabled: bool) -> None:
    if not enabled or shutil.which("git") is None:
        return
    ensure_gitignore(Path(".gitignore"))
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


def run_agent(
    agent_cmd: str,
    resolved_executable: str,
    prompt: str,
    log_path: Path,
    timeout_sec: int,
    phase_name: str = "phase",
    prompt_mode: str = "auto",
    extra_args_str: str = "",
    strict_sandbox: bool = False,
) -> None:
    cmd, stdin_payload = build_agent_command(
        agent_cmd=agent_cmd,
        resolved_executable=resolved_executable,
        prompt=prompt,
        prompt_mode=prompt_mode,
        extra_args_str=extra_args_str,
    )
    popen_kwargs: dict[str, object] = {
        "stdin": subprocess.PIPE if stdin_payload is not None else None,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": build_sanitized_env(strict_sandbox=strict_sandbox),
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    collected: list[str] = []
    timed_out = threading.Event()

    try:
        with subprocess.Popen(cmd, **popen_kwargs) as proc:  # type: ignore[arg-type]
            def _on_timeout() -> None:
                timed_out.set()
                terminate_process_tree(proc)

            timer = threading.Timer(timeout_sec, _on_timeout)
            timer.daemon = True
            timer.start()
            try:
                if stdin_payload is not None and proc.stdin is not None:
                    try:
                        proc.stdin.write(stdin_payload)
                    except BrokenPipeError:
                        pass
                    finally:
                        proc.stdin.close()

                assert proc.stdout is not None
                for line in proc.stdout:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    collected.append(line)
                rc = proc.wait()
            finally:
                timer.cancel()
                terminate_process_tree(proc)
    except OSError as exc:
        raise SystemExit(f"FATAL: Failed to launch '{agent_cmd}': {exc}") from exc

    full_log = "".join(collected)
    log_path.write_text(full_log, encoding="utf-8")
    if timed_out.is_set():
        raise SystemExit(f"FATAL: {phase_name} timed out after {timeout_sec}s. Partial log: {log_path}")
    if rc != 0:
        raise SystemExit(f"FATAL: '{agent_cmd}' exited with status {rc}. See {log_path}")
    check_log_for_fatal_errors(full_log, phase_name, log_path)


def is_qa_pass(qa_path: Path) -> bool:
    if not qa_path.is_file() or qa_path.stat().st_size == 0:
        return False
    lines = [ln.strip() for ln in qa_path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    if not lines:
        return False
    return lines[-1] == "STATUS: PASS"


def append_backlog_gate_failure(qa_path: Path, unchecked: list[str]) -> None:
    """Downgrade a false PASS report when TASKS.md still contains unchecked acceptance criteria."""
    existing = qa_path.read_text(encoding="utf-8", errors="replace").rstrip()
    summary_items = "\n".join(f"- {item}" for item in unchecked[:20])
    extra = (
        "\n\n## Backlog Completion Gate Failure\n"
        f"- **Severity:** `MAJOR`\n"
        f"- **Detail:** {len(unchecked)} acceptance criteria remain unchecked (`- [ ]`) in `./TASKS.md`:\n"
        f"{summary_items}\n\n"
        "STATUS: FAIL\n"
    )
    qa_path.write_text(existing + extra, encoding="utf-8")


def print_summary(passed: bool, iterations_run: int) -> None:
    print("\n=== [RELEASE SUMMARY] ===")
    print(f"Final Verdict : {'PASS' if passed else 'FAIL'}")
    print(f"Iterations Run: {iterations_run}")
    for artifact in ("PRD.md", "TASKS.md", "DESIGN_SPEC.md", "QA_REPORT.md"):
        p = Path(artifact)
        status = f"{p.stat().st_size} bytes" if p.is_file() else "MISSING"
        print(f"  - {artifact}: {status}")
    unfinished = extract_unchecked_tasks(Path("TASKS.md"))
    print(f"Unchecked Tasks: {len(unfinished)}")
    print(f"Logs Directory: {LOG_DIR}")


def execute_pipeline(args: argparse.Namespace) -> int:
    resolved_exec = ensure_prerequisites(args.agent)
    enable_git = not args.no_git

    if args.resume_from == "phase1":
        print("=== [PHASE 1] Project Manager -> PRD.md & TASKS.md ===")
        pm_prompt = f"{ROLE_FILES['pm'].read_text(encoding='utf-8')}\n\nUSER REQUEST:\n{args.resolved_idea}"
        run_agent(
            args.agent,
            resolved_exec,
            pm_prompt,
            LOG_DIR / "phase1.log",
            args.timeout,
            "Phase 1",
            args.prompt_mode,
            args.agent_args,
            args.strict_sandbox,
        )
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
        run_agent(
            args.agent,
            resolved_exec,
            uiux_prompt,
            LOG_DIR / "phase2.log",
            args.timeout,
            "Phase 2",
            args.prompt_mode,
            args.agent_args,
            args.strict_sandbox,
        )
        validate_artifact(Path("DESIGN_SPEC.md"), "Phase 2", r"^#\s+")
        git_checkpoint("phase-2-design-spec", enable_git)

    validate_artifact(Path("PRD.md"), "Phase 3 precondition")
    validate_artifact(Path("TASKS.md"), "Phase 3 precondition")
    validate_artifact(Path("DESIGN_SPEC.md"), "Phase 3 precondition")

    prd_path = Path("PRD.md")
    tasks_path = Path("TASKS.md")
    design_path = Path("DESIGN_SPEC.md")
    qa_path = Path("QA_REPORT.md")
    spec_snapshot = capture_spec_snapshot(prd_path, design_path, tasks_path)
    iterations_run = 0

    for i in range(1, args.max_retries + 1):
        iterations_run = i
        if i == 1 and args.resume_from == "phase4":
            print(f"=== [SKIP] Resuming directly at Phase 4 (Iteration {i}/{args.max_retries}) ===")
        else:
            print(f"=== [PHASE 3 - Iteration {i}/{args.max_retries}] Programmer -> Implementation & Build ===")
            prog_prompt = build_programmer_prompt(
                role_text=ROLE_FILES["programmer"].read_text(encoding="utf-8"),
                iteration=i,
                tasks_path=tasks_path,
                qa_path=qa_path,
            )
            run_agent(
                args.agent,
                resolved_exec,
                prog_prompt,
                LOG_DIR / f"phase3_iter{i}.log",
                args.timeout,
                f"Phase 3 (Iteration {i})",
                args.prompt_mode,
                args.agent_args,
                args.strict_sandbox,
            )
            enforce_spec_integrity(spec_snapshot, prd_path, design_path, tasks_path)
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
        run_agent(
            args.agent,
            resolved_exec,
            qc_prompt,
            LOG_DIR / f"phase4_iter{i}.log",
            args.timeout,
            f"Phase 4 (Iteration {i})",
            args.prompt_mode,
            args.agent_args,
            args.strict_sandbox,
        )
        validate_artifact(qa_path, f"Phase 4 (Iteration {i})", r"^STATUS:\s*(PASS|FAIL)\s*$")

        qa_ok = is_qa_pass(qa_path)
        if qa_ok:
            unfinished = extract_unchecked_tasks(tasks_path)
            if unfinished and not args.allow_incomplete_tasks:
                print(
                    f"=== [WARN] QA_REPORT.md returned STATUS: PASS, but {len(unfinished)} "
                    "unchecked item(s) remain in TASKS.md! Routing back to Programmer... ==="
                )
                append_backlog_gate_failure(qa_path, unfinished)
                qa_ok = False

        shutil.copy2(qa_path, LOG_DIR / f"QA_REPORT.iter{i}.md")
        git_checkpoint(f"phase-4-iter-{i}", enable_git)

        if qa_ok:
            print(f"=== [SUCCESS] Passed QC, Spec Integrity, and Backlog Gate on iteration {i}! ===")
            print_summary(True, iterations_run)
            return 0

        print(f"=== [FAIL] Defects or unfinished tasks remain on iteration {i}. Routing back to Programmer... ===")

    print(f"=== [STOP] Reached max retries ({args.max_retries}). Inspect QA_REPORT.md and {LOG_DIR}/ ===")
    print_summary(False, iterations_run)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    orig_cwd = Path.cwd()
    if args.target_dir:
        template_root = resolve_template_root()
        target_path = Path(args.target_dir).resolve()
        bootstrap_target_dir(target_path, template_root)
        os.chdir(target_path)
    try:
        return execute_pipeline(args)
    finally:
        os.chdir(orig_cwd)


if __name__ == "__main__":
    sys.exit(main())
