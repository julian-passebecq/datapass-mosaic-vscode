# A lightweight tag.
set -euo pipefail
git init -q -b main
printf '%s\n' '.env' 'logs/' '__pycache__/' > .gitignore
sed -i 's/\r$//' scripts/run.sh
chmod +x scripts/run.sh
git add -A
git add --chmod=+x scripts/run.sh
git commit -q -m "chore: import the nightly sales loader"
git tag v0.1.0
