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
