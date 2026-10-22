# Git and shell cheatsheet

Reference for the Learning path "Git and the shell". In the Terminal Lab you type every command yourself in a VS Code
terminal opened in the mission folder; Datapass runs none of them and checks only the resulting files and repository.

## Bash: moving around and looking

| Command | Does |
|---|---|
| `pwd` | print the current folder |
| `ls -la` | list files with details, hidden ones included |
| `cd dir`, `cd ..`, `cd -` | enter a folder, go up, go back |
| `mkdir -p a/b/c` | create the whole path; no error if it exists |
| `mv src dst`, `cp -r src dst` | move or rename, copy a folder |
| `rm file` | delete (there is no recycle bin) |
| `head -n 5 f`, `tail -n 5 f` | first or last lines |
| `wc -l f` | count lines |
| `find . -name '*.csv' -size 0` | find empty CSV files |

## Text tools and pipes

```bash
grep -c ERROR app.log                          # count matching lines
grep -h ERROR logs/*.log | sort | uniq -c | sort -rn | head -5
cut -d, -f2 servers.csv | sort -u              # unique values of column 2 (no quoted commas)
grep -v '^#' config.txt > clean.txt            # drop comments, write a new file
echo "done" >> run.log                         # append
```

`>` replaces a file, `>>` appends, `2>` redirects errors, `>&2` writes to stderr. `uniq` only merges adjacent lines:
sort first.

## Scripts that fail loudly

```bash
#!/usr/bin/env bash
set -euo pipefail
for file in landing/*.csv; do
  if [ ! -s "$file" ]; then
    echo "empty file: $file" >&2
    exit 1
  fi
done
```

- `-e` exits on many command failures, with exceptions for conditionals and command lists; handle expected failures explicitly. `-u` rejects unset variables, and `pipefail` makes a pipeline fail if any command fails.
- `$?` is the last exit code: 0 is success.
- Quote variables: `"$file"`.

## PowerShell equivalents

| bash | PowerShell |
|---|---|
| `ls -la` | `Get-ChildItem -Force` |
| `grep ERROR f` | `Select-String ERROR f` |
| `wc -l f` | `(Get-Content f).Count` |
| `mkdir -p a/b` | `New-Item -ItemType Directory -Force a/b` |
| `cmd1 \| cmd2` (text) | `cmd1 \| cmd2` (objects) |

## Git: the daily loop

```bash
git init
git status --short
git add file.sh            # stage
git diff --staged          # what the next commit contains
git commit -m "fix(loader): skip empty files"
git log --oneline --graph --all
git tag -a v1.0.0 -m "First release"
```

- Working tree → `git add` → index → `git commit` → repository.
- Write `.gitignore` first (`.env`, `.venv/`, data extracts, build output). Ignoring a file does not remove it from
  history; `git rm --cached file` stops tracking it.
- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

## Branches

```bash
git switch -c feature/eur     # create and switch
git switch main
git branch -d feature/eur     # delete a merged branch
```

A branch is a movable pointer to a commit; `HEAD` points to the current branch.

## Combining work

| Command | Result |
|---|---|
| `git merge feature` | merge commit with two parents, or a fast-forward if main did not move |
| `git rebase main` | replays your commits on top of main as new commits (do not rebase shared commits) |
| `git cherry-pick <hash>` | copies one commit onto the current branch |
| `git merge --abort`, `git rebase --abort` | go back to the state before |

Conflict: edit the file between `<<<<<<<`, `=======` and `>>>>>>>`, remove the markers, `git add` it, then
`git commit` or `git rebase --continue`.

## Recovery

```bash
git reflog                       # every position HEAD has had
git branch rescued <hash>        # bring a lost commit back on a branch
git stash push -m "wip"          # set changes aside
git stash list
git stash apply stash@{0}
git restore file                 # discard unstaged changes to a file
```
