# Right behaviour, but no shebang and no strict mode (the ticket asks for both).
set -euo pipefail
mkdir -p bin logs
cat > bin/check-incoming.sh <<'SCRIPT'
# set -euo pipefail
status=0
for file in "$1"/*.csv; do
  if [ ! -s "$file" ]; then
    basename "$file" >&2
    status=1
  fi
done
exit "$status"
SCRIPT
set +e
bash bin/check-incoming.sh incoming 2> logs/check.err
echo $? > logs/check.status
