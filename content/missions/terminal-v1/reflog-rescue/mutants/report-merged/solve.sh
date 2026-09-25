# Recovers everything, then also merges the report branch into main.
set -euo pipefail
tip=$(git log -g --format='%H %gs' HEAD | grep -m1 ' commit: test: quarterly totals$' | cut -d' ' -f1)
git branch feature/quarterly-report "$tip"
git reset -q --hard "$(git log -g --format='%H %gs' HEAD | grep -m1 ' commit: docs: add the on-call runbook$' | cut -d' ' -f1)"
git stash pop -q
git commit -q -am "chore: raise retries to 5"
git merge -q --no-edit feature/quarterly-report
