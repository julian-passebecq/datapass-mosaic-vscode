# Tests the wrong thing (-e: exists) and so names every CSV.
set -euo pipefail
mkdir -p bin logs
cat > bin/check-incoming.sh <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
status=0
for file in "$1"/*.csv; do
  if [ -e "$file" ]; then
    basename "$file" >&2
    status=1
  fi
done
exit "$status"
SCRIPT
set +e
bash bin/check-incoming.sh incoming 2> logs/check.err
echo $? > logs/check.status
