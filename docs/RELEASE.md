# Releasing a new MorfyAI version

Step-by-step notes for shipping a new version. No server to deploy for a
release itself — GitHub Releases hosts everything the app needs
(`checkForUpdate`/`downloadUpdate` in `morfyai/ui/web_panel.py` read straight
from the GitHub Releases API). The only server-side piece is the public
changelog page, which is a separate, optional step at the end.

## 1. Bump the version

- Edit `VERSION` at the repo root (plain string, no leading `v`, e.g. `2.1`).
- Decide the bump by feel, not strict semver: a handful of features/fixes is
  a minor bump (`2.0` → `2.1`); a redesign-scale change is a major bump
  (`1.2` → `2.0`, as happened for the web panel).

## 2. Write the changelog entry

- Add a new `## X.Y — YYYY-MM-DD` section at the **top** of `CHANGELOG.md`
  (newest first). Group with `**Bold subheads**` if there's enough to
  organize (see the `2.0` entry for the pattern); a short flat list is fine
  for a small release.
- This text gets reused twice below (GitHub release notes + changelog.html),
  so write it once, well.

## 3. Build the release zip

```
python tools/release/build_zip.py
```

- Reads `VERSION`, packages every **git-tracked** file (untracked/dev-only
  files are automatically excluded — nothing to hand-curate) into
  `release/MorfyAI-<version>.zip`, laid out as `MorfyAI.json` (drop-in
  package pointer) + `MorfyAI/` (the plugin).
- Also writes `release/MorfyAI-<version>.zip.sha256` — the app verifies the
  download against this before installing.
- `release/` is gitignored; the zip only needs to exist locally long enough
  to upload it in the next step.

## 4. Publish the GitHub release

```
gh release create v<version> release/MorfyAI-<version>.zip release/MorfyAI-<version>.zip.sha256 \
  --repo gemrra/MorfyAI \
  --title "MorfyAI v<version>" \
  --notes "<paste the CHANGELOG.md entry for this version, plus the Install blurb below>"
```

Append this to the notes (same every time):

```
**Install:** download `MorfyAI-<version>.zip`, extract it directly into your Houdini `packages/` folder, restart Houdini.
```

- That's it for the app's update check — `checkForUpdate()` compares
  `VERSION` against the latest GitHub release tag automatically, no other
  step needed for existing installs to see the update.
- **If you already published the tag and need to fix the asset** (e.g. a
  post-release bugfix before anyone's downloaded it): `gh release
  delete-asset v<version> <filename> --yes` then `gh release upload
  v<version> <file>` — don't delete/recreate the whole release unless the
  version number itself is wrong.

## 5. Commit + push

```
git add VERSION CHANGELOG.md
git commit -m "..."
git push origin main
```

(Plus whatever code changes the release actually contains, obviously.)

## 6. (Optional) Update the public changelog page

Only needed if the release is worth announcing to end users browsing in a
browser, not just the in-app update check.

- Edit the `RELEASES` array at the top of the changelog page's `<script>`
  block — prepend one object (newest first), remove `latest: true` from the
  previous top entry. Same shape as a `CHANGELOG.md` entry, just JS objects:
  `{ version, date, title, latest, changes: [{ type, text }, ...] }`
  (`type` ∈ `new` | `improved` | `fixed` | `changed` | `release`).
- The live file lives on `naraserver` (ZimaOS) at
  `/DATA/AppData/morfyai/changelog/changelog.html`, served by the
  `morfyai-changelog` container on port `18789`, reverse-proxied to
  `morfyfx.com/morfyai/changelog` via Nginx Proxy Manager. To update it:

  ```
  scp changelog.html naraserver:/DATA/AppData/morfyai/changelog/changelog.html
  ```

  No container restart needed — nginx serves the file straight off disk.
