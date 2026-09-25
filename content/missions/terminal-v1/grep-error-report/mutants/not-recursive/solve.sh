# One level of folders only: logs/archive/<day>/ is missed.
set -euo pipefail
mkdir -p report
grep -h ' ERROR ' logs/*/*.log | sort -u > report/errors.txt
grep -o 'E[0-9]\{4\}' report/errors.txt | sort -u > report/codes.txt
