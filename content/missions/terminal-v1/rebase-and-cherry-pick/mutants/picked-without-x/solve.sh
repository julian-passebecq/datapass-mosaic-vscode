# The cherry-pick does not record where the fix came from.
set -euo pipefail
git switch -q feature/batch-api
GIT_SEQUENCE_EDITOR="sed -i -e '/ WIP debug prints\$/s/^pick/drop/'" git rebase -q -i main
git switch -q release/1.2
git cherry-pick feature/batch-api
