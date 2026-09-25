# Right merge, but the branch is left behind.
set -euo pipefail
git merge --no-ff feature/eur-reporting || true
printf '%s\n' 'pipeline: nightly-sales' 'schedule: "0 2 * * *"' 'timezone: Europe/Paris' 'currency: EUR' 'retries: 3' > config/settings.yml
git add config/settings.yml
git commit -q --no-edit
