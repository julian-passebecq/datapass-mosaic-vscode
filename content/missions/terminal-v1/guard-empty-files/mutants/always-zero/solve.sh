# Reports the empty files but always exits 0: the scheduler would go on with the load.
set -euo pipefail
mkdir -p bin logs
cat > bin/check-incoming.sh <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
for file in "$1"/*.csv; do
  if [ ! -s "$file" ]; then
    basename "$file" >&2
  fi
done
exit 0
SCRIPT
set +e
bash bin/check-incoming.sh incoming 2> logs/check.err
echo $? > logs/check.status
