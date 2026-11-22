# Terminal Multi-Agent Coding Team (PM, UI/UX, Programmer, QC Tester)

Panduan lengkap ini berisi seluruh konfigurasi *role*, orkestrator, dan *script* eksekusi untuk menjalankan tim agen *coding* otonom di lingkungan terminal CLI agent (seperti Antigravity `agy` CLI atau terminal agent lainnya) dengan kontrak artefak berbasis disk, validasi *gate* antar-fase, checkpoint Git otomatis, dan verifikasi *build/test* nyata.

---

## 1. Struktur Direktori Repository

```text
agent_purnomo/
├── .gitignore
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
├── run_team.py              # Orchestrator Python 3 cross-platform (Windows/macOS/Linux)
├── run-team.ps1             # Orchestrator native Windows PowerShell
└── run-team.sh              # Orchestrator Bash (Linux/macOS/Git Bash)
```

---

## 2. Peningkatan & Kontrak Orkestrasi

Pipeline ini menerapkan proteksi rekayasa untuk mencegah kegagalan diam-diam (*silent failure*) saat dijalankan di proyek nyata:

1. **Template Output Terstruktur**: Setiap file di `.agent/roles/` menyertakan *Required Output Template* sehingga struktur `PRD.md`, `TASKS.md`, `DESIGN_SPEC.md`, dan `QA_REPORT.md` konsisten antar-fase.
2. **Artifact Validation Gates**: Script runner selalu memverifikasi bahwa file artefak fase sebelumnya benar-benar ada dan tidak kosong sebelum melanjutkan ke fase berikutnya.
3. **Proteksi Stale `QA_REPORT.md`**: Sebelum Phase 4 dijalankan pada tiap iterasi, `QA_REPORT.md` lama otomatis diarsipkan ke `.agent/logs/` agar baris `STATUS: PASS` lama tidak menyebabkan *false positive*.
4. **Verdict Matching Ketat**: Runner hanya menerima status lulus jika baris non-kosong terakhir dari `QA_REPORT.md` persis `STATUS: PASS`.
5. **Progres Task & Defect-First**: `programmer.md` memprioritaskan perbaikan bug `CRITICAL`/`MAJOR` dari `QA_REPORT.md` terlebih dahulu, lalu mencentang `- [x]` pada `TASKS.md` setiap tugas terverifikasi.
6. **Safe Process & Port Cleanup**: `qc.md` mengutamakan *in-process test client* (`TestClient`, `supertest`, `pytest`, `vitest`) atau mewajibkan *timeout* dan `trap` cleanup PID agar server tidak pernah menggantung atau membocorkan port.
7. **Git Checkpoint Otomatis**: Setiap fase dan iterasi otomatis di-commit sebagai checkpoint (`--no-git` untuk menonaktifkan) serta seluruh stdout/stderr dicatat di `.agent/logs/`.

---

## 3. Cara Menjalankan

### Opsi A: Mode Interaktif (`/dev-team` di dalam CLI Agent)
Buka terminal di *root* proyekmu, jalankan CLI agent (`agy` atau terminal agent pilihanmu), lalu panggil *workflow*-nya:

```text
/dev-team Buatkan aplikasi CLI & web dashboard monitoring harga crypto real-time. Override: gunakan Python FastAPI + SQLite untuk backend, React Tailwind untuk frontend.
```

### Opsi B: Cross-Platform Python Runner (`run_team.py`) — Direkomendasikan
Berjalan identik di Windows, macOS, dan Linux tanpa dependensi eksternal (hanya Python 3):

```bash
python run_team.py "Buat aplikasi web catatan keuangan pribadi dengan grafik pengeluaran bulanan"
```

Opsi CLI yang tersedia:
```bash
python run_team.py \
  --agent agy \
  --max-retries 3 \
  --resume-from phase1 \
  --timeout 1800 \
  "Buat REST API manajemen tugas dengan FastAPI dan SQLite"
```

### Opsi C: Windows PowerShell (`run-team.ps1`)
```powershell
.\run-team.ps1 -Idea "Buat REST API manajemen tugas" -AgentCmd "agy" -MaxRetries 3
# Atau resume dari Phase 3 setelah edit manual:
.\run-team.ps1 -ResumeFrom phase3
```

### Opsi D: Linux / macOS Bash (`run-team.sh`)
```bash
chmod +x run-team.sh
./run-team.sh --agent agy --max-retries 3 "Buat aplikasi web catatan keuangan pribadi"
# Atau resume dari Phase 3:
./run-team.sh --resume-from phase3
```

---

## 4. Ringkasan Flag Runner

| Flag (`run_team.py` / `run-team.sh`) | Parameter PowerShell (`run-team.ps1`) | Default | Fungsi |
| :--- | :--- | :--- | :--- |
| `--agent <cmd>` | `-AgentCmd <cmd>` | `agy` | Binary CLI agent (`agy`, `gemini`, `claude`, dll.) |
| `--max-retries <n>` | `-MaxRetries <n>` | `3` | Batas maksimum iterasi loop Phase 3–4 |
| `--resume-from <phase>` | `-ResumeFrom <phase>` | `phase1` | Lanjutkan dari `phase1`, `phase2`, `phase3`, atau `phase4` |
| `--timeout <sec>` | *(Python only)* | `1800` | Batas waktu eksekusi per pemanggilan fase |
| `--no-git` | `-NoGit` | `false` | Nonaktifkan auto-init & checkpoint commit Git |
