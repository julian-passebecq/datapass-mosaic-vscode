# A plain rebase: linear, but the WIP commit is still there.
set -euo pipefail
git switch -q feature/batch-api
git rebase -q main
git switch -q release/1.2
git cherry-pick -x feature/batch-api
