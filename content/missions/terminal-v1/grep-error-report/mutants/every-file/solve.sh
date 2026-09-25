# Every file, not only the .log files: the .bak copy and the README come along.
set -euo pipefail
mkdir -p report
grep -rh 'ERROR' logs | sort -u > report/errors.txt
grep -o 'E[0-9]\{4\}' report/errors.txt | sort -u > report/codes.txt
