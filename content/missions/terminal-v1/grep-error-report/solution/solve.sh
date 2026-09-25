# Reference solution (bash), played by scripts/terminal_missions_smoke.py in the mission folder.
set -euo pipefail
mkdir -p report
find logs -type f -name '*.log' -exec grep -h ' ERROR ' {} + | sort -u > report/errors.txt
grep -o 'E[0-9]\{4\}' report/errors.txt | sort -u > report/codes.txt
