# grep -r prefixes every line with its file name.
set -euo pipefail
mkdir -p report
grep -r --include='*.log' ' ERROR ' logs | sort -u > report/errors.txt
grep -o 'E[0-9]\{4\}' report/errors.txt | sort -u > report/codes.txt
