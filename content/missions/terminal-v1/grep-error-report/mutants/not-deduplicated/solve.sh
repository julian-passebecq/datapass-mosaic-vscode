# sort without -u: the line logged again by the rerun appears twice.
set -euo pipefail
mkdir -p report
find logs -type f -name '*.log' -exec grep -h ' ERROR ' {} + | sort > report/errors.txt
grep -o 'E[0-9]\{4\}' report/errors.txt | sort -u > report/codes.txt
