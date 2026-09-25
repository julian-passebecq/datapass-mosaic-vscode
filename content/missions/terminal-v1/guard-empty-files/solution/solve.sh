# Reference solution (bash), played by scripts/terminal_missions_smoke.py in the mission folder.
set -euo pipefail
mkdir -p bin logs
cat > bin/check-incoming.sh <<'SCRIPT'
#!/usr/bin/env bash
# Names the empty CSV files of a folder on stderr and exits 1 if there is one, so the scheduler stops the load.
set -euo pipefail
folder="${1:?usage: check-incoming.sh <folder>}"
status=0
for file in "$folder"/*.csv; do
  if [ ! -s "$file" ]; then
    basename "$file" >&2
    status=1
  fi
done
exit "$status"
SCRIPT
chmod +x bin/check-incoming.sh
set +e
bash bin/check-incoming.sh incoming 2> logs/check.err
echo $? > logs/check.status
