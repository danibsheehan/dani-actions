# dani-actions

Reusable GitHub Actions workflows shared across personal project repos, so a fix or
improvement lands once instead of being hand-copied into every repo.

## Workflows

### `dependabot-auto-merge.yml`

Auto-merges only the grouped `npm-minor-and-patch` Dependabot PRs once required checks
pass. Ungrouped npm majors, gomod, and github-actions bumps stay manual since they carry
more upgrade risk.

Call it from a consuming repo:

```yaml
name: Dependabot auto-merge

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: write
  pull-requests: write

jobs:
  auto-merge:
    uses: danibsheehan/dani-actions/.github/workflows/dependabot-auto-merge.yml@v1
```

Pin to a tag (`@v1`), not `@main` — a future change here shouldn't silently affect a
consumer that hasn't opted in yet.

### `deploy-github-pages.yml`

Build + deploy to GitHub Pages, parameterized since the build command, output path, and
whether client-side routing needs the `404.html` SPA-fallback trick genuinely differ per
app. No cross-job artifact download — build and deploy happen in the same workflow run, so
there's no artifact-poisoning risk class to defend against.

Call it from a consuming repo (gate it on your own CI job passing first):

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  quality:
    # ... your existing lint/test/build job ...

  deploy:
    needs: quality
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    permissions:
      contents: read
      pages: write
      id-token: write
    uses: danibsheehan/dani-actions/.github/workflows/deploy-github-pages.yml@v2
    with:
      build-command: npm run build
      dist-path: dist
      spa-fallback: true # only if the app has client-side routes
    secrets: inherit
```

Pin to `@v2` (this workflow was added after `@v1`, which only had `dependabot-auto-merge.yml`
— existing `@v1` references are unaffected and don't need to change).
