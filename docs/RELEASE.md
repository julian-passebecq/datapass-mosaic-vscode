# Releasing the extension

A release is a GitHub Release with the packaged VSIX attached. It is published by
`.github/workflows/release.yml` when a tag `v<version>` is pushed. Nothing is published to the VS Code Marketplace.

1. On a branch, set the new `version` in `package.json` and `package-lock.json` (both `version` lines at the top),
   move the `## [Unreleased]` items of `CHANGELOG.md` into a new `## [<version>] - <date>` section, and update the
   compare links at the bottom. `npm test` (`scripts/package_smoke.mjs`) fails if `package.json`'s version has no
   section.
2. Merge that pull request on green CI.
3. Tag the merge commit on `main` and push the tag:

   ```bash
   git fetch origin
   git tag v<version> origin/main
   git push origin v<version>
   ```

4. The Release workflow checks that the tag equals `v` + `package.json`'s version, builds like the CI `extension` job
   (`npm ci`, `npm run package`, `npm test`), and creates the release with `datapass-mosaic-vscode-<version>.vsix`
   and that version's changelog section as notes.

If the workflow fails before the release exists, fix it on `main`, then move the tag
(`git push origin :refs/tags/v<version>`, tag again, push). Once a release is published, prefer a new patch version
over rewriting it.

To install a release: download the VSIX and run `code --install-extension datapass-mosaic-vscode-<version>.vsix`.
