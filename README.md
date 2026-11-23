# Terminal Multi-Agent Coding Team (PM, UI/UX, Programmer, QC Tester)

Panduan lengkap ini berisi seluruh konfigurasi *role*, orkestrator, unit test, dan *script* eksekusi untuk menjalankan tim agen *coding* otonom di lingkungan terminal CLI agent (`agy`, `claude`, `gemini`, `codex`) dengan kontrak artefak berbasis disk, proteksi integritas spesifikasi, isolasi process-tree, checkpoint Git otomatis, dan verifikasi *build/test* nyata.

---

## 1. Struktur Direktori Repository

```text
agent_purnomo/
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml           # GitHub Actions CI (Linux + Windows unittest & syntax checks)
├── .agent/
│   ├── roles/
│   │   ├── pm.md            # Senior Technical PM -> PRD.md & TASKS.md (dengan template skema)
│   │   ├── uiux.md          # Principal UI/UX Designer -> DESIGN_SPEC.md (dengan template skema)
│   │   ├── programmer.md    # Senior Fullstack Engineer -> Kode, build, update [x] TASKS.md
│   │   └── qc.md            # Lead QA Auditor -> Automated tests, safe cleanup, QA_REPORT.md
│   ├── workflows/
│   │   └── dev-team.md      # Slash-command orchestrator (/dev-team) dengan isolasi sub-agent
│   └── logs/                # (Auto-generated & gitignored) Log eksekusi, snapshot frozen & arsip QA
├── examples/
│   └── sample-output/       # Contoh referensi output PRD, TASKS, DESIGN_SPEC, QA_REPORT
├── tests/
│   └── test_run_team.py     # Zero-dependency unittest suite (11 unit & e2e tests)
├── run_team.py              # Orchestrator Python 3 cross-platform (direkomendasikan)
├── run-team.ps1             # Orchestrator native Windows PowerShell
└── run-team.sh              # Orchestrator Bash (Linux/macOS/Git Bash)
```

---

## 2. Peningkatan & Kontrak Keamanan Orkestrasi

1. **Cryptographic Spec-Freeze & Anti-Tamper Guard**: Setelah Phase 2, `PRD.md`, `DESIGN_SPEC.md`, dan daftar kriteria di `TASKS.md` dikunci. Jika Programmer memodifikasi spesifikasi atau menghapus checkbox `- [ ]` pada Phase 3, runner otomatis memulihkannya.
2. **Process-Tree Isolation & Hard Timeout Cleanup**: Setiap fase dijalankan pada *process group* terisolasi (`CREATE_NEW_PROCESS_GROUP` / `start_new_session=True`). Jika timeout (`--timeout`) tercapai atau proses berakhir, seluruh pohon proses (`taskkill /F /T` / `os.killpg`) dihentikan sehingga tidak ada zombie dev server yang membocorkan port.
3. **Silent CLI Fatal Error Scanner**: Memindai log output tiap fase terhadap error fatal seperti `RateLimitError`, `insufficient_quota`, `AuthenticationError`, atau `invalid_api_key` meski binary CLI keluar dengan status `0`.
4. **Strict Sandbox Environment (`--strict-sandbox`)**: Opsional menghapus token sensitif host (`GITHUB_TOKEN`, `GH_TOKEN`, `AWS_*`, `AZURE_*`, `NPM_TOKEN`, `PYPI_TOKEN`, `SSH_AUTH_SOCK`) sebelum menjalankan proses agen.
5. **Bootstrap Proyek Target (`--target-dir` / `-TargetDir`)**: Jalankan pipeline dari repo pusat menuju folder proyek baru mana pun; `.agent/` dan `.gitignore` otomatis di-*scaffold* bila belum ada.
6. **Adapter Multi-CLI & Auto-Stdin Fallback (`--prompt-mode`)**: Mendukung `agy`, `claude` (`--dangerously-skip-permissions`), `gemini`, dan `codex` (`--full-auto`), serta otomatis beralih ke `stdin` di Windows untuk prompt > 8.000 karakter atau wrapper `.cmd`/`.bat`.
7. **Focused Retry Injection & Backlog Completion Gate**: Menyuntikkan `BUG-XX` + item `- [ ]` yang belum selesai ke Phase 3 saat retry, mengarsipkan `QA_REPORT.md` basi sebelum Phase 4, dan menolak `STATUS: PASS` palsu jika masih ada `- [ ]` di `TASKS.md`.
8. **Auto-`.gitignore` Safety Guard sebelum `git add -A`**: Memastikan `.agent/logs/`, `.env`, `node_modules/`, `.venv/`, dan `*.db` selalu diabaikan sebelum checkpoint commit Git dibuat.

---

## 3. Cara Menjalankan

### Opsi A: Mode Interaktif (`/dev-team` di dalam CLI Agent)
```text
/dev-team Buatkan aplikasi CLI & web dashboard monitoring harga crypto real-time. Override: gunakan Python FastAPI + SQLite untuk backend, React Tailwind untuk frontend.
```

### Opsi B: Cross-Platform Python Runner (`run_team.py`) — Direkomendasikan
```bash
# Jalankan ke folder proyek target baru dengan proteksi penuh:
python run_team.py \
  --target-dir D:\Projek\task-app \
  --agent agy \
  --strict-sandbox \
  --max-retries 3 \
  --timeout 900 \
  "Buat REST API manajemen tugas dengan FastAPI dan SQLite"
```

### Opsi C: Windows PowerShell (`run-team.ps1`)
```powershell
.\run-team.ps1 -TargetDir "D:\Projek\task-app" -Idea "Buat REST API manajemen tugas" -AgentCmd "agy" -MaxRetries 3
```

### Opsi D: Linux / macOS Bash (`run-team.sh`)
```bash
chmod +x run-team.sh
./run-team.sh --target-dir ~/projects/task-app --agent agy --max-retries 3 "Buat aplikasi web catatan keuangan pribadi"
```

---

## 4. Ringkasan Flag Runner

| Flag (`run_team.py` / `run-team.sh`) | Parameter PowerShell (`run-team.ps1`) | Default | Fungsi |
| :--- | :--- | :--- | :--- |
| `--target-dir <dir>` | `-TargetDir <dir>` | *(CWD)* | Target folder proyek (auto-scaffold `.agent/` & `.gitignore`) |
| `--agent <cmd>` | `-AgentCmd <cmd>` | `agy` | Binary CLI agent (`agy`, `claude`, `gemini`, `codex`) |
| `--agent-args "<args>"` | *(Python only)* | `""` | Argumen tambahan yang diteruskan ke CLI agent |
| `--prompt-mode <mode>` | `-PromptMode <mode>` | `auto` | Pengiriman prompt: `auto`, `arg`, atau `stdin` |
| `--max-retries <n>` | `-MaxRetries <n>` | `3` | Batas maksimum iterasi loop Phase 3–4 |
| `--resume-from <phase>` | `-ResumeFrom <phase>` | `phase1` | Lanjutkan dari `phase1`, `phase2`, `phase3`, atau `phase4` |
| `--timeout <sec>` | *(Python only)* | `1800` | Batas waktu eksekusi per fase (kill process tree) |
| `--strict-sandbox` | *(Python only)* | `false` | Hapus env var token host sensitif sebelum spawn agen |
| `--allow-incomplete-tasks` | `-AllowIncompleteTasks` | `false` | Izinkan `STATUS: PASS` walau masih ada `- [ ]` di `TASKS.md` |
| `--no-git` | `-NoGit` | `false` | Nonaktifkan auto-init & checkpoint commit Git |

---

## 5. Menjalankan Unit Test Orchestrator

```bash
python -W error -m unittest discover -s tests -v
```
