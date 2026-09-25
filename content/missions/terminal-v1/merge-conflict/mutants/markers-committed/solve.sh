# Commits the file with the conflict markers still in it.
set -euo pipefail
git merge --no-ff feature/eur-reporting || true
git add config/settings.yml
git commit -q --no-edit
git branch -q -d feature/eur-reporting
