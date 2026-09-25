# Recreates the branch at main: the name is back, its commits are not.
set -euo pipefail
git branch feature/quarterly-report main
git reset -q --hard "$(git log -g --format='%H %gs' HEAD | grep -m1 ' commit: docs: add the on-call runbook$' | cut -d' ' -f1)"
git stash pop -q
git commit -q -am "chore: raise retries to 5"
