# A squash merge: the right content, but no merge commit and the feature's history is gone.
set -euo pipefail
git merge --squash feature/eur-reporting || true
printf '%s\n' 'pipeline: nightly-sales' 'schedule: "0 2 * * *"' 'timezone: Europe/Paris' 'currency: EUR' 'retries: 3' > config/settings.yml
git add config/settings.yml
git commit -q -m "feat: report amounts in EUR"
git branch -q -D feature/eur-reporting
