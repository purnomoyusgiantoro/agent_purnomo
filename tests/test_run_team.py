import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_team  # noqa: E402


MOCK_AGENT_SCRIPT = r"""import sys
import time
from pathlib import Path

args = sys.argv[1:]
prompt = ""
if "-p" in args:
    idx = args.index("-p")
    if idx + 1 < len(args):
        prompt = args[idx + 1]
    else:
        prompt = sys.stdin.read()
else:
    prompt = sys.stdin.read()

if "SLEEP_FOREVER" in prompt:
    time.sleep(10)
    sys.exit(0)

if "Senior Technical Project Manager" in prompt:
    Path("PRD.md").write_text("# PRD\n\n## 1. Executive Summary\nMock PRD\n", encoding="utf-8")
    Path("TASKS.md").write_text(
        "# Tasks\n\n### TASK-01: Setup\n- [ ] Create app\n- [ ] Verify build\n",
        encoding="utf-8",
    )
elif "Principal Product UI/UX Designer" in prompt:
    Path("DESIGN_SPEC.md").write_text("# Design Spec\n\nMock UI/UX\n", encoding="utf-8")
elif "Senior Fullstack Software Engineer" in prompt:
    state_file = Path(".mock_prog_runs")
    runs = int(state_file.read_text(encoding="utf-8")) + 1 if state_file.is_file() else 1
    state_file.write_text(str(runs), encoding="utf-8")
    Path(".mock_last_prog_prompt.txt").write_text(prompt, encoding="utf-8")
    Path("app.py").write_text("print('hello')\n", encoding="utf-8")
    if runs == 1:
        # Simulate leaving one checkbox unfinished on first run
        Path("TASKS.md").write_text(
            "# Tasks\n\n### TASK-01: Setup\n- [x] Create app\n- [ ] Verify build\n",
            encoding="utf-8",
        )
    else:
        Path("TASKS.md").write_text(
            "# Tasks\n\n### TASK-01: Setup\n- [x] Create app\n- [x] Verify build\n",
            encoding="utf-8",
        )
elif "Lead QA Automation Engineer" in prompt:
    state_file = Path(".mock_qc_runs")
    runs = int(state_file.read_text(encoding="utf-8")) + 1 if state_file.is_file() else 1
    state_file.write_text(str(runs), encoding="utf-8")
    if runs == 1:
        Path("QA_REPORT.md").write_text(
            "# QA Report\n\n### BUG-01: Missing check\n- **Severity:** `CRITICAL`\n\nSTATUS: FAIL\n",
            encoding="utf-8",
        )
    else:
        Path("QA_REPORT.md").write_text(
            "# QA Report\n\nAll tests passed.\n\nSTATUS: PASS\n",
            encoding="utf-8",
        )
else:
    sys.stderr.write("Unknown role prompt\n")
    sys.exit(2)
"""


def _write_mock_wrapper(tmp_path: Path) -> Path:
    mock_agent = tmp_path / "mock_agent.py"
    mock_agent.write_text(MOCK_AGENT_SCRIPT, encoding="utf-8")
    if os.name == "nt":
        wrapper = tmp_path / "mock-agy.cmd"
        wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{mock_agent}" %*\r\n', encoding="utf-8")
    else:
        wrapper = tmp_path / "mock-agy"
        wrapper.write_text(f'#!/usr/bin/env bash\n"{sys.executable}" "{mock_agent}" "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
    return wrapper


class RunTeamUnitTests(unittest.TestCase):
    def test_is_qa_pass_strict_last_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qa = Path(tmp) / "QA_REPORT.md"
            qa.write_text("Previous line said STATUS: PASS\n\nSTATUS: FAIL\n\n", encoding="utf-8")
            self.assertFalse(run_team.is_qa_pass(qa))

            qa.write_text("# Report\n\nAll good.\nSTATUS: PASS  \r\n\n", encoding="utf-8")
            self.assertTrue(run_team.is_qa_pass(qa))

    def test_extract_unchecked_tasks_and_defects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = Path(tmp) / "TASKS.md"
            tasks.write_text(
                "# Backlog\n### TASK-01: Init\n- [x] Done\n- [ ] Pending one\n### TASK-02: API\n- [ ] Pending two\n",
                encoding="utf-8",
            )
            unchecked = run_team.extract_unchecked_tasks(tasks)
            self.assertEqual(unchecked, ["[TASK-01] Pending one", "[TASK-02] Pending two"])

            qa = Path(tmp) / "QA_REPORT.md"
            qa.write_text(
                "# QA\n### BUG-01: Crash\n- **Severity:** `CRITICAL`\n- **Location:** `app.py:10`\nSTATUS: FAIL\n",
                encoding="utf-8",
            )
            defects = run_team.extract_qa_defects(qa)
            self.assertIn("### BUG-01: Crash", defects)
            self.assertTrue(any("CRITICAL" in line for line in defects))

    def test_spec_snapshot_and_anti_tamper_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            prd = p / "PRD.md"
            design = p / "DESIGN_SPEC.md"
            tasks = p / "TASKS.md"

            original_prd = "# PRD\n\nKeep auth guard\n"
            original_design = "# Design\n\nBlue #38BDF8\n"
            prd.write_text(original_prd, encoding="utf-8")
            design.write_text(original_design, encoding="utf-8")
            tasks.write_text(
                "# Tasks\n### TASK-01: Auth\n- [ ] Add JWT guard\n- [ ] Verify 401\n",
                encoding="utf-8",
            )

            snap = run_team.capture_spec_snapshot(prd, design, tasks)

            # Simulate programmer tampering: overwriting specs & deleting a checkbox
            prd.write_text("# PRD\n\nRemoved auth\n", encoding="utf-8")
            design.write_text("# Design\n\nChanged\n", encoding="utf-8")
            tasks.write_text("# Tasks\n### TASK-01: Auth\n- [x] Add JWT guard\n", encoding="utf-8")

            warnings = run_team.enforce_spec_integrity(snap, prd, design, tasks)
            self.assertEqual(len(warnings), 3)
            self.assertEqual(prd.read_text(encoding="utf-8"), original_prd)
            self.assertEqual(design.read_text(encoding="utf-8"), original_design)
            self.assertEqual(run_team.extract_unchecked_tasks(tasks), ["[TASK-01] Verify 401"])

    def test_silent_fatal_log_detector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "phase.log"
            run_team.check_log_for_fatal_errors("All tests passed cleanly.\n", "Phase 3", log)
            with self.assertRaises(SystemExit):
                run_team.check_log_for_fatal_errors("Error: RateLimitError - 429 too many requests\n", "Phase 3", log)
            with self.assertRaises(SystemExit):
                run_team.check_log_for_fatal_errors("Provider returned insufficient_quota", "Phase 1", log)

    def test_build_sanitized_env_strict_sandbox(self) -> None:
        sample = {
            "PATH": "/usr/bin",
            "GITHUB_TOKEN": "ghp_secret",
            "AWS_SECRET_ACCESS_KEY": "aws_secret",
            "AZURE_CLIENT_SECRET": "az_secret",
            "OPENAI_API_KEY": "keep_for_cli",
        }
        relaxed = run_team.build_sanitized_env(strict_sandbox=False, base_env=sample)
        self.assertIn("GITHUB_TOKEN", relaxed)

        strict = run_team.build_sanitized_env(strict_sandbox=True, base_env=sample)
        self.assertNotIn("GITHUB_TOKEN", strict)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", strict)
        self.assertNotIn("AZURE_CLIENT_SECRET", strict)
        self.assertIn("PATH", strict)
        self.assertIn("OPENAI_API_KEY", strict)

    def test_ensure_gitignore_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gi = Path(tmp) / ".gitignore"
            gi.write_text("custom.log\n.env\n", encoding="utf-8")
            run_team.ensure_gitignore(gi)
            first_pass = gi.read_text(encoding="utf-8")
            self.assertIn("custom.log", first_pass)
            self.assertIn(".agent/logs/", first_pass)
            self.assertIn("node_modules/", first_pass)

            run_team.ensure_gitignore(gi)
            self.assertEqual(first_pass, gi.read_text(encoding="utf-8"))

    def test_build_agent_command_adapters_and_stdin(self) -> None:
        cmd, stdin_data = run_team.build_agent_command("claude", "/usr/bin/claude", "hello", "arg", "")
        self.assertEqual(cmd, ["/usr/bin/claude", "--dangerously-skip-permissions", "-p", "hello"])
        self.assertIsNone(stdin_data)

        cmd_stdin, stdin_data2 = run_team.build_agent_command("claude", "/usr/bin/claude", "long prompt", "stdin", "")
        self.assertEqual(cmd_stdin, ["/usr/bin/claude", "--dangerously-skip-permissions", "-p"])
        self.assertEqual(stdin_data2, "long prompt")

    def test_backlog_completion_gate_downgrades_false_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qa = Path(tmp) / "QA_REPORT.md"
            qa.write_text("# QA\n\nAll good.\n\nSTATUS: PASS\n", encoding="utf-8")
            self.assertTrue(run_team.is_qa_pass(qa))
            run_team.append_backlog_gate_failure(qa, ["[TASK-02] Implement auth"])
            self.assertFalse(run_team.is_qa_pass(qa))
            self.assertIn("Backlog Completion Gate Failure", qa.read_text(encoding="utf-8"))

    def test_validate_artifact_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "PRD.md"
            with self.assertRaises(SystemExit):
                run_team.validate_artifact(missing, "Phase 1")

            missing.write_text("No heading", encoding="utf-8")
            with self.assertRaises(SystemExit):
                run_team.validate_artifact(missing, "Phase 1", r"^#\s+")

            missing.write_text("# Valid Heading\n", encoding="utf-8")
            run_team.validate_artifact(missing, "Phase 1", r"^#\s+")

    def test_run_agent_timeout_terminates_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wrapper = _write_mock_wrapper(tmp_path)
            log_file = tmp_path / "timeout.log"
            with self.assertRaises(SystemExit) as ctx:
                run_team.run_agent(
                    agent_cmd=str(wrapper),
                    resolved_executable=str(wrapper),
                    prompt="SLEEP_FOREVER",
                    log_path=log_file,
                    timeout_sec=1,
                    phase_name="TimeoutTest",
                    prompt_mode="stdin",
                )
            self.assertIn("timed out after 1s", str(ctx.exception))

    def test_target_dir_bootstrap_and_end_to_end_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template_dir = tmp_path / "template_repo"
            (template_dir / ".agent" / "roles").mkdir(parents=True)
            (template_dir / ".agent" / "workflows").mkdir(parents=True)
            (template_dir / ".agent" / "roles" / "pm.md").write_text("Senior Technical Project Manager", encoding="utf-8")
            (template_dir / ".agent" / "roles" / "uiux.md").write_text("Principal Product UI/UX Designer", encoding="utf-8")
            (template_dir / ".agent" / "roles" / "programmer.md").write_text("Senior Fullstack Software Engineer", encoding="utf-8")
            (template_dir / ".agent" / "roles" / "qc.md").write_text("Lead QA Automation Engineer", encoding="utf-8")
            (template_dir / ".agent" / "workflows" / "dev-team.md").write_text("workflow", encoding="utf-8")

            wrapper = _write_mock_wrapper(tmp_path)
            target_project = tmp_path / "new_project"
            orig_cwd = Path.cwd()
            try:
                os.chdir(template_dir)
                rc = run_team.main(
                    [
                        "--target-dir",
                        str(target_project),
                        "--agent",
                        str(wrapper),
                        "--max-retries",
                        "3",
                        "--strict-sandbox",
                        "--no-git",
                        "Build a mock app",
                    ]
                )
            finally:
                os.chdir(orig_cwd)

            self.assertEqual(rc, 0)
            self.assertTrue((target_project / ".gitignore").is_file())
            self.assertTrue((target_project / "PRD.md").is_file())
            self.assertTrue((target_project / "TASKS.md").is_file())
            self.assertTrue((target_project / "DESIGN_SPEC.md").is_file())
            self.assertTrue((target_project / "QA_REPORT.md").is_file())
            self.assertTrue(run_team.is_qa_pass(target_project / "QA_REPORT.md"))
            self.assertEqual(run_team.extract_unchecked_tasks(target_project / "TASKS.md"), [])
            self.assertTrue((target_project / ".agent" / "logs" / "QA_REPORT.before-iter2.md").is_file())
            retry_prompt = (target_project / ".mock_last_prog_prompt.txt").read_text(encoding="utf-8")
            self.assertIn("BUG-01", retry_prompt)
            self.assertIn("Verify build", retry_prompt)


if __name__ == "__main__":
    unittest.main()
