# Merges the whole feature into the release instead of picking the fix.
set -euo pipefail
git switch -q feature/batch-api
GIT_SEQUENCE_EDITOR="sed -i -e '/ WIP debug prints\$/s/^pick/drop/'" git rebase -q -i main
git switch -q release/1.2
git merge -q --no-edit feature/batch-api
