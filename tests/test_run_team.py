import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_team  # noqa: E402


MOCK_AGENT_SCRIPT = r"""import os
import sys
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

            mock_agent = tmp_path / "mock_agent.py"
            mock_agent.write_text(MOCK_AGENT_SCRIPT, encoding="utf-8")

            # Create cross-platform wrapper executable for mock agent
            if os.name == "nt":
                wrapper = tmp_path / "mock-agy.cmd"
                wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{mock_agent}" %*\r\n', encoding="utf-8")
            else:
                wrapper = tmp_path / "mock-agy"
                wrapper.write_text(f'#!/usr/bin/env bash\n"{sys.executable}" "{mock_agent}" "$@"\n', encoding="utf-8")
                wrapper.chmod(0o755)

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
