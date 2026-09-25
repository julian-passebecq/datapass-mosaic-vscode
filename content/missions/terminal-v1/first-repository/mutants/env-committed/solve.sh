# Commits everything first, then adds the .gitignore: .env stays tracked.
set -euo pipefail
git init -q -b main
sed -i 's/\r$//' scripts/run.sh
chmod +x scripts/run.sh
git add -A
git add --chmod=+x scripts/run.sh
git commit -q -m "chore: import the nightly sales loader"
printf '%s\n' '.env' 'logs/' '__pycache__/' > .gitignore
git add .gitignore
git commit -q -m "chore: ignore secrets and generated files"
git tag -a v0.1.0 -m "v0.1.0"
