# Public history and release audit

This repository includes `scripts/audit-public-history.sh` as a maintainer review
aid. It inventories all objects reachable from the local Git references and
flags:

- private-export, key, firmware and package-like filenames;
- historical documentation images;
- blobs of at least 1 MiB;
- selected private-key and labelled-secret patterns in text blobs;
- branches, remote-tracking references and tags included in the scan.

Run it from a complete local checkout:

```bash
git fetch --all --tags --prune
bash scripts/audit-public-history.sh
```

The report and supporting inventories are written below `.git/history-audit/`
by default, so they remain outside the working tree and cannot be committed
accidentally. A different output directory may be passed as the first argument.

## Scope limits

The scanner is conservative and produces false positives. Documentation can
legitimately contain words such as `AppKey`, placeholder values or password
filenames. Every match requires manual review.

The scanner only sees objects available in the local clone and reachable from
its references. Before relying on it, fetch all branches and tags. GitHub release
assets are separate from Git history and must be downloaded and inspected
independently. Automatically generated source archives reflect the commit
currently referenced by a tag; manually uploaded archives remain separate
release assets.

## Decision order

1. **Real credential found:** rotate or invalidate it first. Deleting a release,
   branch or commit does not make an already copied credential safe.
2. **Private export or runtime state found:** preserve a private recovery copy,
   remove the public artifact and plan a rewrite covering every affected ref.
3. **Third-party screenshot, logo or product photograph only:** replace it on
   `main`. Decide separately whether the historical copy justifies a targeted
   rewrite; do not squash unrelated engineering history by default.
4. **No sensitive finding:** keep the history. Rewriting public tags and releases
   creates its own compatibility and provenance costs.

Any rewrite should be rehearsed in a disposable clone, followed by a fresh clone
and a second audit. Prefer removing exact paths or blobs with `git filter-repo`
over collapsing the repository to one commit. Coordinate tag and release changes
between the gateway and adapter repositories.
