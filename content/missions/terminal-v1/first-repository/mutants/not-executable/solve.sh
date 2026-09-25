# Forgets the executable bit.
set -euo pipefail
git init -q -b main
printf '%s\n' '.env' 'logs/' '__pycache__/' > .gitignore
sed -i 's/\r$//' scripts/run.sh
git add -A
git commit -q -m "chore: import the nightly sales loader"
git tag -a v0.1.0 -m "v0.1.0"
