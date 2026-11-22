#!/usr/bin/env bash
set -euo pipefail

IDEA="${1:?Masukkan deskripsi proyek. Contoh: ./run-team.sh 'Buat REST API manajemen tugas'}"
MAX_RETRIES=3

# Sesuaikan perintah CLI agent di bawah ini dengan binary CLI yang terpasang (misal: agy / gemini / claude)
AGENT_CMD="agy"

echo "=== [PHASE 1] Project Manager -> PRD.md & TASKS.md ==="
$AGENT_CMD -p "$(cat .agent/roles/pm.md)

USER REQUEST:
$IDEA"

echo "=== [PHASE 2] UI/UX Designer -> DESIGN_SPEC.md ==="
$AGENT_CMD -p "$(cat .agent/roles/uiux.md)

Read ./PRD.md and ./TASKS.md from the current directory and generate ./DESIGN_SPEC.md."

for i in $(seq 1 $MAX_RETRIES); do
  echo "=== [PHASE 3 - Iterasi $i/$MAX_RETRIES] Programmer -> Implementasi & Build ==="
  $AGENT_CMD -p "$(cat .agent/roles/programmer.md)

Read ./PRD.md, ./TASKS.md, ./DESIGN_SPEC.md, and ./QA_REPORT.md (if present). Implement/fix code and verify build in terminal."

  echo "=== [PHASE 4 - Iterasi $i/$MAX_RETRIES] QC Tester -> Automated Test & Audit ==="
  $AGENT_CMD -p "$(cat .agent/roles/qc.md)

Read ./PRD.md, ./TASKS.md, and ./DESIGN_SPEC.md. Write and run automated tests in terminal, then output ./QA_REPORT.md."

  if grep -q "STATUS: PASS" QA_REPORT.md 2>/dev/null; then
    echo "=== [SUCCESS] Lolos QC pada iterasi ke-$i! ==="
    exit 0
  fi

  echo "=== [FAIL] Ditemukan bug di QA_REPORT.md. Mengulang ke Programmer... ==="
done

echo "=== [STOP] Mencapai batas maksimal $MAX_RETRIES iterasi. Cek QA_REPORT.md untuk detail sisa bug. ==="
exit 1
