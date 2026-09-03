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
there's no artifact-poisoning risk class to defend against. Name the caller file
`deploy-pages.yml` in the consuming repo — see [File naming conventions](#file-naming-conventions).

Call it from a consuming repo's `deploy-pages.yml` (a separate file from your verify
workflow — it has a different trigger, push-to-`main` only, and a different risk profile,
since it has side effects):

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

**If your build needs secret values baked in** (e.g. a Vite app embedding `VITE_*` vars at
build time): the `secrets` context can't be referenced inside `with:` — GitHub Actions
disallows that for `workflow_call` jobs, only plain values/`github.*`/`vars.*` expressions
are allowed there. Map your repo's actual secrets onto the 3 generic pass-through slots
instead, and reference them by their generic env var name in `build-command`:

```yaml
  deploy:
    needs: quality
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    permissions:
      contents: read
      pages: write
      id-token: write
    uses: danibsheehan/dani-actions/.github/workflows/deploy-github-pages.yml@v3
    with:
      build-command: >-
        VITE_SUPABASE_URL="$BUILD_SECRET_1"
        VITE_SUPABASE_ANON_KEY="$BUILD_SECRET_2"
        VITE_AI_SERVICE_URL="$BUILD_SECRET_3"
        npm run build
      dist-path: dist
      spa-fallback: true
    secrets:
      build-secret-1: ${{ secrets.VITE_SUPABASE_URL }}
      build-secret-2: ${{ secrets.VITE_SUPABASE_ANON_KEY }}
      build-secret-3: ${{ secrets.VITE_AI_SERVICE_URL }}
```

`secrets: inherit` and an explicit `secrets:` mapping are mutually exclusive on the same
job — use the explicit mapping whenever you need to rename a secret onto one of the generic
slots. If your build needs no secrets at all, `secrets: inherit` (as in the example above)
is simpler and still correct — the generic slots just stay empty. Pin to `@v3` for this
pattern (`@v2` predates the generic secret slots).

### `npm-verify.yml`

Each verification concern (format, doc-drift checks, lint, audit, typecheck, test, build,
one-off extra checks) is its own parallel job, matrixed over `packages` — so a repo with
more than one npm package (e.g. a root app plus a separate `service/`) gets one check per
package per concern, instead of one blob job. Path-filtering (skip a job's real work on PRs
that don't touch its paths) happens with a step-level `if` inside each job, not a job-level
one — a job skipped entirely via job-level `if` never posts a check run, which would leave a
required check pending forever on a PR that never trips it.

```yaml
name: verify

on:
  pull_request:
  push:
    branches: [main]

jobs:
  verify:
    permissions:
      contents: read
      pull-requests: write
      checks: write # the Cobertura PR-comment step creates a check run, not just a comment
    uses: danibsheehan/dani-actions/.github/workflows/npm-verify.yml@v7
    with:
      packages: |
        [{"name": "app", "path": ".", "test-command": "npm run test:coverage",
          "build-command": "npm run build", "coverage-file": "coverage/cobertura-coverage.xml"}]
      doc-check-commands: |
        [{"name": "stack-docs", "command": "python3 .github/scripts/check_stack_docs.py"}]
```

**`packages`** (required) — a JSON array of package objects:

| field | required | default | meaning |
|---|---|---|---|
| `name` | yes | — | shown in the check name, e.g. `lint (app)` |
| `path` | yes | — | working directory for this package |
| `test-command` | yes | — | e.g. `npm run test:coverage` |
| `build-command` | yes | — | e.g. `npm run build` |
| `paths` | no | `""` (never filtered) | a full `dorny/paths-filter` block *including* the `app:` key, e.g. `"app:\n  - 'src/**'"` |
| `audit` | no | `true` | set `false` to skip the `audit` job for this package |
| `typecheck-command` | no | `""` (no typecheck job) | e.g. `npm run typecheck` — omit when type-checking is already inseparable from `build` (Angular's AOT/Ivy template checking has no standalone equivalent) |
| `coverage-file` | no | `""` (no coverage steps) | relative to `path` |
| `setup-chrome` | no | `false` | installs a real Chrome before `test-command` (e.g. Angular's test runner) |

Other inputs, all optional: `node-version-file` (default `.nvmrc`), `doc-check-commands`
(JSON array of `{name, command}`, always run at repo root, never path-filtered — for
cross-cutting drift checks), `extra-checks` (JSON array of `{name, command, path, paths}`,
path-filtered like a package — for one-off verification that isn't lint/format/test/build,
e.g. an OpenAPI contract check), `coverage-thresholds` (default `"50 75"`), `skip-covered`
(default `true`). Needs a secret baked into a `test-command`/`build-command`? Same generic
`build-secret-1/2/3` pass-through as `deploy-github-pages.yml` (`secrets` can't be referenced
inside `with:`).

**Note on required-check names:** calling a reusable workflow's job from a job named
`verify` renders each check as `verify / <job name>` — e.g. `verify / lint (app)`, `verify /
test (app)` — not the bare job name. Get the exact strings from a real PR's checks (`gh pr
checks <n>`) before setting your branch ruleset's required checks, not by guessing from this
doc.

Pin to `@v7` for this workflow (`npm-quality-gate.yml`, the single-job predecessor to this
workflow, is removed as of `@v7` — repos still pinned to `@v4`/`@v5`/`@v6` are unaffected,
since tags are immutable, but there's no reason to pin a new consumer to it).

### `codeql-js.yml`

CodeQL scanning for a repo with only JavaScript/TypeScript to analyze. A repo with more than
one language to scan (Go, GitHub Actions itself, etc.) needs its own bespoke `codeql.yml`
instead — see caught-looking's for the pattern (a `matrix` plus an explicit Go build step,
since CodeQL's autobuild heuristic hangs when `go.mod` isn't at the repo root).

**Before adding this to a repo for the first time**, check whether GitHub's *default*
(automatic) CodeQL setup is already enabled — `gh api repos/<owner>/<repo>/code-scanning/default-setup
--jq .state`. Default and advanced (workflow-based) setup cannot coexist: every SARIF upload
from this workflow gets rejected with "CodeQL analyses from advanced configurations cannot
be processed when the default setup is enabled" until default setup is disabled (`gh api -X
PATCH repos/<owner>/<repo>/code-scanning/default-setup -f state=not-configured`).

```yaml
name: CodeQL

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '17 3 * * 1' # weekly, Monday

permissions:
  contents: read

concurrency:
  group: codeql-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  analyze:
    permissions:
      contents: read
      security-events: write
    uses: danibsheehan/dani-actions/.github/workflows/codeql-js.yml@v8
```

Pin to `@v8` for this workflow.

### `dependency-review.yml`

Flags newly-introduced vulnerable or license-incompatible dependencies in a PR's diff,
before merge — complements Dependabot, which is retroactive/scheduled rather than PR-time.
Works across every ecosystem GitHub's dependency graph covers (npm and Go both included),
so it's identical across every consuming repo regardless of stack.

```yaml
name: Dependency review

on:
  pull_request:

jobs:
  dependency-review:
    permissions:
      contents: read
      pull-requests: write
    uses: danibsheehan/dani-actions/.github/workflows/dependency-review.yml@v8
```

Optional input: `fail-on-severity` (default `"high"`). Pin to `@v8` for this workflow.

### `pr-guide.yml`

Scaffolds an empty/default PR description, posts a sticky checklist comment, and applies
path-based area labels. Generalizes only the *orchestration* (checkout pinned to the base
commit, diff collection, comment posting, labeling) — the area taxonomy itself (what counts
as "editor" vs "sync", which verify commands and reviewer-focus notes apply to each) is
genuinely repo-specific and stays local: every consuming repo owns its own
`.github/scripts/generate_pr_guide.py` + `.github/scripts/pr_guide_lib.py` (and
`generate_pr_body.py`, which is close to identical everywhere but still repo-owned since
it's checked out at the trusted base commit, not fetched from here).

```yaml
name: PR guide

on:
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review]

jobs:
  guide:
    uses: danibsheehan/dani-actions/.github/workflows/pr-guide.yml@v9
    with:
      labels: |
        [{"name": "area: app", "color": "c2e0c6", "description": "App shell, layout, or routing"}]
```

`labels` is optional (default `"[]"`) — `actions/labeler` auto-creates missing labels on its
own given `issues: write`, just without curated colors/descriptions, so only pass this if
you want those. Pin to `@v9` for this workflow.

**Note on trigger choice:** use `pull_request_target` with `synchronize` included, not plain
`pull_request` — the guide/labels then stay current as the PR evolves rather than freezing
at open-time, and pinning checkout to `pull_request.base.sha` already fully avoids running
PR-authored code, so there's no additional safety a same-repo-only plain `pull_request`
trigger would buy over this.

### `lighthouse-ci.yml`

Audits a local production build with Lighthouse CI and posts a sticky PR comment with report
links. This is the right approach for a GitHub-Pages-only repo with no PR-preview
infrastructure — it audits the build directly rather than a live URL. A repo with real
PR-preview infra (e.g. Cloudflare Pages branch previews) should audit that live URL instead,
since it reflects real network/CDN conditions a local static-dir audit can't; that's a
different, bespoke setup this workflow doesn't try to cover.

```yaml
name: Lighthouse CI

on: pull_request

jobs:
  lighthouse:
    if: github.event.pull_request.draft == false
    permissions:
      contents: read
      pull-requests: write
    uses: danibsheehan/dani-actions/.github/workflows/lighthouse-ci.yml@v10
    with:
      build-command: npm run build
```

Requires a `.lighthouserc.json` at the repo root with `collect.staticDistDir` pointing at
the build output — **`treosh/lighthouse-ci-action` has no such input of its own**, this
setting only exists in the config file. Recommended baseline, informational (warn-level)
thresholds:

```json
{
  "ci": {
    "collect": { "staticDistDir": "./dist", "numberOfRuns": 1 },
    "assert": {
      "assertions": {
        "categories:performance": ["warn", { "minScore": 0.8 }],
        "categories:accessibility": ["warn", { "minScore": 0.9 }],
        "categories:best-practices": ["warn", { "minScore": 0.9 }],
        "categories:seo": ["warn", { "minScore": 0.9 }]
      }
    },
    "upload": { "target": "temporary-public-storage" }
  }
}
```

Optional inputs: `node-version-file` (default `.nvmrc`), `lighthouserc-path` (default
`./.lighthouserc.json`). Pin to `@v10` for this workflow.

## File naming conventions

Every consuming repo should name its workflow files by what they do, not by a generic
umbrella term — `ci.yml`/`test.yml` doesn't say whether it lints, tests, deploys, or all
three. Same target/purpose = same filename across every repo that has it:

- **`verify.yml`** — the parallel PR/push verification jobs (calls `npm-verify.yml`)
- **`deploy-pages.yml`** — GitHub Pages deploys (calls `deploy-github-pages.yml`)
- **`deploy-cloud-run.yml`** — Cloud Run deploys (repo-specific, no shared workflow yet)
- **`codeql.yml`** — CodeQL scanning (calls `codeql-js.yml` for JS/TS-only repos; bespoke
  for multi-language repos)
- **`dependency-review.yml`** — calls the reusable workflow of the same name
- **`pr-guide.yml`** — calls the reusable workflow of the same name
- **`dependabot-auto-merge.yml`**, **`pr-labels.yml`** — already-standardized
  single-purpose workflows

A repo with two deploy targets (e.g. a Pages-hosted app plus a Cloud-Run-hosted service)
gets both `deploy-pages.yml` and `deploy-cloud-run.yml` as separate files — never a single
`deploy.yml` covering both, since "what does this deploy, and where" should be answerable
from the filename alone.
