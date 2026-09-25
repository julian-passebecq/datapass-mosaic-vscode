# Reference solution (bash), played by scripts/terminal_missions_smoke.py in the mission folder.
set -euo pipefail
git switch -q main
# The merge stops on the conflict (exit 1).
git merge --no-ff feature/eur-reporting || true
cat > config/settings.yml <<'YAML'
pipeline: nightly-sales
schedule: "0 2 * * *"
timezone: Europe/Paris
currency: EUR
retries: 3
YAML
git add config/settings.yml
git commit -q --no-edit
git branch -q -d feature/eur-reporting
