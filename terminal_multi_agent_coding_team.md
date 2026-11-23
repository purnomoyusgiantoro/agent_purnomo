# Terminal Multi-Agent Coding Team (PM, UI/UX, Programmer, QC Tester)

Panduan lengkap ini berisi seluruh konfigurasi *role*, orkestrator, unit test, dan *script* eksekusi untuk menjalankan tim agen *coding* otonom di lingkungan terminal CLI agent (`agy`, `claude`, `gemini`, `codex`) dengan kontrak artefak berbasis disk, validasi *gate* antar-fase, checkpoint Git otomatis, dan verifikasi *build/test* nyata.

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
│   │   └── dev-team.md      # Slash-command orchestrator (/dev-team)
│   └── logs/                # (Auto-generated & gitignored) Log eksekusi & arsip QA_REPORT
├── examples/
│   └── sample-output/       # Contoh referensi output PRD, TASKS, DESIGN_SPEC, QA_REPORT
├── tests/
│   └── test_run_team.py     # Zero-dependency unittest suite untuk orchestrator
├── run_team.py              # Orchestrator Python 3 cross-platform (direkomendasikan)
├── run-team.ps1             # Orchestrator native Windows PowerShell
└── run-team.sh              # Orchestrator Bash (Linux/macOS/Git Bash)
```

---

## 2. Peningkatan & Kontrak Orkestrasi

1. **Bootstrap Proyek Target (`--target-dir` / `-TargetDir`)**: Jalankan pipeline dari repo pusat menuju folder proyek baru mana pun; `.agent/` dan `.gitignore` otomatis di-*scaffold* bila belum ada.
2. **Adapter Multi-CLI & Auto-Stdin Fallback (`--prompt-mode`)**: Mendukung adapter otomatis untuk `agy`, `claude` (`--dangerously-skip-permissions`), `gemini`, dan `codex` (`--full-auto`), serta otomatis beralih ke pengiriman prompt via `stdin` pada Windows saat prompt melebihi 8.000 karakter atau melalui `.cmd`/`.bat` wrapper untuk mencegah error panjang command-line (`WinError 206`).
3. **Focused Retry Prompt Injection**: Pada iterasi perbaikan (`i > 1`), daftar `BUG-XX` dari `QA_REPORT.md` dan checkbox `- [ ]` yang belum selesai di `TASKS.md` otomatis disuntikkan ke prompt Programmer.
4. **Backlog Completion Gate**: `STATUS: PASS` dari `QA_REPORT.md` hanya diterima jika seluruh checkbox `- [ ]` di `TASKS.md` sudah dicentang `- [x]` (bisa di-*bypass* dengan `--allow-incomplete-tasks`).
5. **Proteksi Stale `QA_REPORT.md` & Strict Verdict Matching**: Sebelum Phase 4, `QA_REPORT.md` lama diarsipkan ke `.agent/logs/` dan status lulus hanya valid jika baris non-kosong terakhir persis `STATUS: PASS`.
6. **Auto-`.gitignore` Safety Guard sebelum `git add -A`**: Memastikan `.agent/logs/`, `.env`, `node_modules/`, `.venv/`, dan `*.db` selalu diabaikan sebelum checkpoint commit Git dibuat.
7. **Safe Process & Port Cleanup**: `qc.md` mewajibkan *in-process test client* (`TestClient`, `supertest`, `pytest`, `vitest`) atau timeout + `trap` cleanup PID agar server uji tidak pernah menggantung.

---

## 3. Cara Menjalankan

### Opsi A: Mode Interaktif (`/dev-team` di dalam CLI Agent)
```text
/dev-team Buatkan aplikasi CLI & web dashboard monitoring harga crypto real-time. Override: gunakan Python FastAPI + SQLite untuk backend, React Tailwind untuk frontend.
```

### Opsi B: Cross-Platform Python Runner (`run_team.py`) — Direkomendasikan
```bash
# Jalankan langsung ke folder proyek target baru dari mana saja:
python run_team.py --target-dir /path/to/proyek-baru "Buat aplikasi catatan keuangan pribadi"

# Dengan opsi lengkap (misal menggunakan Claude CLI):
python run_team.py \
  --target-dir D:\Projek\task-app \
  --agent claude \
  --prompt-mode auto \
  --max-retries 3 \
  --timeout 1800 \
  "Buat REST API manajemen tugas dengan FastAPI dan SQLite"
```

### Opsi C: Windows PowerShell (`run-team.ps1`)
```powershell
.\run-team.ps1 -TargetDir "D:\Projek\task-app" -Idea "Buat REST API manajemen tugas" -AgentCmd "agy" -MaxRetries 3
# Resume dari Phase 3:
.\run-team.ps1 -TargetDir "D:\Projek\task-app" -ResumeFrom phase3
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
| `--timeout <sec>` | *(Python only)* | `1800` | Batas waktu eksekusi per fase |
| `--allow-incomplete-tasks` | `-AllowIncompleteTasks` | `false` | Izinkan `STATUS: PASS` walau masih ada `- [ ]` di `TASKS.md` |
| `--no-git` | `-NoGit` | `false` | Nonaktifkan auto-init & checkpoint commit Git |

---

## 5. Menjalankan Unit Test Orchestrator

```bash
python -W error -m unittest discover -s tests -v
```
