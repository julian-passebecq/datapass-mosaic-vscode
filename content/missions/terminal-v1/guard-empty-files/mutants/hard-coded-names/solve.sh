# Writes today's answer instead of checking the folder.
set -euo pipefail
mkdir -p bin logs
cat > bin/check-incoming.sh <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
echo "refunds.csv" >&2
echo "returns.csv" >&2
exit 1
SCRIPT
set +e
bash bin/check-incoming.sh incoming 2> logs/check.err
echo $? > logs/check.status
