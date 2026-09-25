# git stash apply: the change is committed but the entry stays in the stash.
set -euo pipefail
tip=$(git log -g --format='%H %gs' HEAD | grep -m1 ' commit: test: quarterly totals$' | cut -d' ' -f1)
git branch feature/quarterly-report "$tip"
git reset -q --hard "$(git log -g --format='%H %gs' HEAD | grep -m1 ' commit: docs: add the on-call runbook$' | cut -d' ' -f1)"
git stash apply -q
git commit -q -am "chore: raise retries to 5"
