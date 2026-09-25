# Reference solution (bash), played by scripts/terminal_missions_smoke.py in the mission folder.
set -euo pipefail
# HEAD's reflog remembers both lost commits (the stash also left a "reset: moving to HEAD" entry on top).
found() { git log -g --format='%H %gs' HEAD | grep -m1 " commit: $1\$" | cut -d' ' -f1; }
git branch feature/quarterly-report "$(found 'test: quarterly totals')"
git reset -q --hard "$(found 'docs: add the on-call runbook')"
git stash pop -q
git commit -q -am "chore: raise retries to 5"
