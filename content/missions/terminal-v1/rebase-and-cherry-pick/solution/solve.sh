# Reference solution (bash), played by scripts/terminal_missions_smoke.py in the mission folder.
# The interactive rebase gets its todo list edited by sed instead of an editor: `drop` on the WIP line.
set -euo pipefail
git switch -q feature/batch-api
GIT_SEQUENCE_EDITOR="sed -i -e '/ WIP debug prints\$/s/^pick/drop/'" git rebase -q -i main
git switch -q release/1.2
git cherry-pick -x feature/batch-api
