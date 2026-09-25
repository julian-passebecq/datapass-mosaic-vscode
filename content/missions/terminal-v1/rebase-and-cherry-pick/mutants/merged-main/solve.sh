# Merges main into the branch instead of rebasing it: a merge commit, and the WIP commit stays. The backport is right.
set -euo pipefail
git switch -q feature/batch-api
git merge -q --no-edit main
git switch -q release/1.2
git cherry-pick -x ':/fix: reject empty batches'
