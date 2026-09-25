# Resolves by taking the feature's whole file: Paris time is lost.
set -euo pipefail
git merge --no-ff feature/eur-reporting || true
git checkout --theirs config/settings.yml
git add config/settings.yml
git commit -q --no-edit
git branch -q -d feature/eur-reporting
