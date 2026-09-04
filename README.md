# dani-actions

Reusable GitHub Actions workflows shared across Danielle's personal project repos, so a fix
or improvement lands once instead of being hand-copied into every repo.

**In plain English:** every project needs to run the same kinds of checks before code ships —
does it build, do the tests pass, is a dependency insecure, should this get deployed. Rather
than write that checklist separately in each project and let the copies quietly drift apart,
this repo holds the actual, working checklist once. Each project just points at it and says
which version to use.

_Everything past this point is the technical reference — what each workflow does and how a
project wires it in._

## Versioning

Every tag is cumulative — a new tag only adds or fixes workflows, it never removes or
breaks an existing one. **All consuming repos pin every `danibsheehan/dani-actions/...`
reference to the same tag: the latest one**, even for a workflow whose content hasn't
changed since an earlier tag. When a new tag lands, sweep every repo's `.github/workflows/`
and bump every reference to match — not just the one that motivated the release. This keeps
"what version of dani-actions is repo X on" a single, unambiguous number instead of a
per-workflow patchwork.

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
    uses: danibsheehan/dani-actions/.github/workflows/dependabot-auto-merge.yml@v10
```

Pin to a tag, not `@main` — a future change here shouldn't silently affect a consumer that
hasn't opted in yet. See [Versioning](#versioning) above for which tag.

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
    uses: danibsheehan/dani-actions/.github/workflows/deploy-github-pages.yml@v10
    with:
      build-command: npm run build
      dist-path: dist
      spa-fallback: true # only if the app has client-side routes
    secrets: inherit
```

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
    uses: danibsheehan/dani-actions/.github/workflows/deploy-github-pages.yml@v10
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
is simpler and still correct — the generic slots just stay empty.

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
    uses: danibsheehan/dani-actions/.github/workflows/npm-verify.yml@v10
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

`npm-quality-gate.yml`, the single-job predecessor to this workflow, was removed as of `v7`
— repos still pinned to `@v4`/`@v5`/`@v6` are unaffected, since tags are immutable, but
there's no reason to pin a new consumer to it. See [Versioning](#versioning) above.

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
    uses: danibsheehan/dani-actions/.github/workflows/codeql-js.yml@v10
```

See [Versioning](#versioning) above.

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
    uses: danibsheehan/dani-actions/.github/workflows/dependency-review.yml@v10
```

Optional input: `fail-on-severity` (default `"high"`). See [Versioning](#versioning) above.

### `pr-guide.yml`

Scaffolds an empty/default PR description, posts a sticky checklist comment, and applies
path-based area labels. Both the orchestration (checkout pinned to the base commit, diff
collection, comment posting, labeling) *and* the underlying engine (path→area matching, PR
body scaffolding/merging, guide-comment assembly) are generic — the only thing a consuming
repo owns is a declarative `.github/pr-guide-areas.yml` (consumed by the
[`pr-guide-engine`](#pr-guide-engine) composite action). This replaces what used to be ~200
lines of near-identical Python hand-copied into every repo's `.github/scripts/`.

```yaml
name: PR guide

on:
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review]

jobs:
  guide:
    uses: danibsheehan/dani-actions/.github/workflows/pr-guide.yml@v10
    with:
      labels: |
        [{"name": "area: app", "color": "c2e0c6", "description": "App shell, layout, or routing"}]
```

`labels` is optional (default `"[]"`) — `actions/labeler` auto-creates missing labels on its
own given `issues: write`, just without curated colors/descriptions, so only pass this if
you want those. See [Versioning](#versioning) above.

**Note on trigger choice:** use `pull_request_target` with `synchronize` included, not plain
`pull_request` — the guide/labels then stay current as the PR evolves rather than freezing
at open-time, and pinning checkout to `pull_request.base.sha` already fully avoids running
PR-authored code, so there's no additional safety a same-repo-only plain `pull_request`
trigger would buy over this.

### `pr-guide-engine`

Composite action (used internally by `pr-guide.yml`, not called directly by consuming
repos) implementing the generic PR-guide logic — path→area matching, verify-command/
checklist/reviewer-focus assembly, PR-body scaffolding and merging, and the sticky guide
comment's full layout. Everything it needs beyond the changed-paths list comes from the
caller's own `.github/pr-guide-areas.yml`.

**Two verify-command strategies**, since real callers genuinely differ, not just in area
names:
- `verify_strategy: grouped` (default) — named command groups (`verify_groups`); each area
  optionally sets `verify_group: <name>`, and the *first* touched area's group (in area
  order, or `verify_order` if given) wins exclusively — matching an `if`/`elif` "pick one
  full command block" pattern. Areas may also always-additively contribute `verify_extra`
  regardless of which group won.
- `verify_strategy: additive` — each area independently contributes its own
  `verify_commands` list; touched areas' contributions are unioned (de-duplicated,
  first-occurrence order), with no exclusive grouping.

**Config schema** (`.github/pr-guide-areas.yml`):

```yaml
match_mode: prefix_or_contains  # or prefix_only
verify_strategy: grouped        # or additive
checklist_position: start       # or end -- where always_checklist_items land
# Optional per-function order overrides (default: area declaration order below). A real
# caller's bespoke functions did NOT all iterate areas in the same order -- never assume one
# order fits verify/checklist/reviewer_focus uniformly.
verify_order: [...]
checklist_order: [...]
reviewer_focus_order: [...]

meta_start: "<!-- pr-guide-meta:start -->"
meta_end: "<!-- pr-guide-meta:end -->"
summary_prompt: "<!-- What changed and why? -->"
verify_prompt: "<!-- Commands run, manual checks, or N/A with rationale. -->"
legacy_template_markers: ["## Checklist", "No unintended secrets"]
extra_body_line: null  # optional line inserted before the meta block, e.g. a local-check hint
meta_block_template: "**Touches:** {touches}\n\n..."

guide_intro: "_Auto-generated from changed paths...._"
commit_overflow_note: "_...and {n} more_"  # {n} = commits beyond the first 15
required_checks_description: "Required checks: [verify]({ci_href}) runs ...."
ci_workflow_path: .github/workflows/verify.yml
pr_template_path: .github/pull_request_template.md
no_touches_text: "none detected"

always_checklist_items: ["No unintended secrets or local-only config committed"]
fallback:
  verify: "N/A - docs/tooling only; confirm locally if anything user-facing changed"
  reviewer_focus: "Scope looks docs- or tooling-only; confirm there is no hidden runtime impact"
tests_missing_rule:  # optional
  tests_area_id: tests
  trigger_areas: [editor, sync, database]
  note: "Tests added or updated for changed behavior, or noted why not"
test_file_rule:  # optional
  suffixes: [".test.ts", ".test.tsx"]
  substrings: [".test.", ".spec."]
  note: "Test assertions cover the behavior under review rather than only implementation details"
verify_groups:  # only used when verify_strategy: grouped
  full_suite: ["`npm run lint`", "`npm run format:check`", "`npm run test:run`", "`npm run build`"]

areas:
  - id: editor
    display: "editor"
    prefixes: ["src/components/Editor.tsx", "..."]
    checklist: ["..."]                 # plain strings, or {text, unless_area} to suppress
    reviewer_focus: ["..."]            # conditionally when another area is also touched
    verify_group: full_suite           # grouped strategy only
    verify_extra: ["..."]              # grouped strategy only, always-additive
    verify_commands: ["..."]           # additive strategy only
  - id: other-area
    ...
other_display: "other"
```

An item in `checklist`/`reviewer_focus`/`verify_extra`/`verify_commands` can be a plain
string, or `{text: "...", unless_area: <id>}` to suppress it when a specific other area is
*also* touched (e.g. a generic handler-shape note that's redundant once a more specific
API-contract note already covers the same change).

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
`./.lighthouserc.json`). See [Versioning](#versioning) above.

### `health-probe.yml`

A rare drift check for a deployed backend — not a chatty uptime monitor, so it won't wake a
scale-to-zero Cloud Run revision more than the caller's own schedule allows.

```yaml
name: Weekly probe smoke

on:
  schedule:
    - cron: "17 13 * * 1" # offset each caller's minute to avoid a shared-cron stampede
  workflow_dispatch:

jobs:
  probe:
    uses: danibsheehan/dani-actions/.github/workflows/health-probe.yml@v11
    with:
      url: ${{ vars.API_PUBLIC_URL }}
      paths: '["/health", "/ready"]'
```

**Pass the base URL via a repository *variable*, not a secret.** A service deployed with
`--allow-unauthenticated` is already public — often already embedded in a shipped frontend
bundle — so there's no real confidentiality to protect, and unlike `secrets.*`, `vars.*` can
be referenced directly in a `workflow_call` job's `with:` block, no generic secret-passthrough
slot needed. If an existing caller currently stores this URL as a secret, reclassify it: set
a same-named repository variable with the actual value (you'll need to already know or look
up the value — GitHub secrets are write-only, there's no way to read one back to copy it into
the new variable) and switch every reference from `secrets.X` to `vars.X`, including any
build step that bakes the same URL into a frontend bundle.

Optional inputs: `retries` (default `5`), `retry-delay-seconds` (default `5`),
`timeout-seconds` (default `15`). See [Versioning](#versioning) above.

### `go-verify.yml`

Reusable Go verification gate for a single Go module — `lint` (golangci-lint) and
`test-build` (vet, govulncheck, test+coverage, build) as two parallel jobs, each its own
required check, mirroring `npm-verify.yml`'s job split. Not matrixed over multiple modules
like `npm-verify.yml`'s `packages` input: there's exactly one real caller (caught-looking's
`backend/`) to design a multi-module schema against today, so that array is deferred until a
second Go consumer actually exists — see [Versioning](#versioning)'s spirit of not
speculatively generalizing ahead of real usage.

```yaml
jobs:
  backend:
    if: github.event_name != 'pull_request' || github.event.pull_request.draft == false
    permissions:
      contents: read
      pull-requests: write
      checks: write
    uses: danibsheehan/dani-actions/.github/workflows/go-verify.yml@v12
    with:
      working-directory: backend
      paths: "app:\n  - 'backend/**'\n  - 'Makefile'\n  - '.github/workflows/verify.yml'"
      coverage-threshold: "0.50"
      coverage-label: "Backend coverage"
```

**Coverage is enforced on every push and PR, not just same-repo PRs.**
`5monkeys/cobertura-action`'s own `minimum_coverage`/`fail_below_threshold` inputs only take
effect inside its PR-comment step, which needs a write token and is gated to same-repo
`pull_request` events — it never runs on a push to `main`, and never enforces on a forked
PR. `go-verify.yml` instead enforces via a standalone `check-cobertura-threshold` composite
action step that runs unconditionally on every event; `cobertura-action`'s comment stays
purely informational (`fail_below_threshold: false`), matching its original bespoke
behavior in caught-looking.

Two composite actions back the coverage pipeline, both generic (not caught-looking-specific)
fixes for a `gocover-cobertura` quirk and a threshold check any Go module could need:
`setup-go-env` (checkout + Go via `go-version-file`, mirrors `setup-npm-env`),
`merge-cobertura-by-file` (collapses gocover-cobertura's duplicate per-file `<class>`
entries), and `check-cobertura-threshold` (fails below a minimum line-rate).

Other inputs: `go-version-file` (default `"go.mod"`), `race` (default `true`),
`govulncheck-version` (default `"v1.7.0"`, pinned rather than `@latest`),
`coverage-thresholds` (badge yellow/red, default `"50 75"`), `skip-covered` (default
`true`), `report-name` (default `"backend"`). `golangci-lint` itself is still invoked as
`@latest` in the `lint` job, matching its prior bespoke behavior — not pinned as part of this
extraction.

### `deploy-cloud-run.yml`

Explicit `docker build`/`docker push` to a named Artifact Registry repo, then
`google-github-actions/deploy-cloudrun` (with `image:`, not `source:`) to deploy. Deliberately
not `deploy-cloudrun`'s `source:` input, which hands the build off to a managed Cloud Build
you don't control — the owned registry gives SHA-tagged images (an audit trail of exactly
what's deployed), a retention/cleanup policy (`artifact-keep-count`), and inline build logs
in the Actions run.

```yaml
jobs:
  deploy:
    permissions:
      contents: read
      id-token: write
    uses: danibsheehan/dani-actions/.github/workflows/deploy-cloud-run.yml@v13
    with:
      service-name: my-service
      region: ${{ vars.GCP_REGION }}
      project-id: ${{ vars.GCP_PROJECT_ID }}
      artifact-repository: ${{ vars.GCP_ARTIFACT_REPOSITORY }}
      workload-identity-provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
      deploy-service-account: ${{ vars.GCP_DEPLOY_SERVICE_ACCOUNT }}
      source-path: backend
      startup-probe-path: /health
      smoke-check-paths: '["/health", "/ready"]'
      env-vars-json: '{"SOME_CONFIG": "${{ vars.SOME_CONFIG }}"}'
```

**Auth is Workload Identity Federation only — no service-account key ever touches GitHub.**
Each consuming GCP project needs its own WIF pool + provider bound to a deploy service
account (`roles/iam.workloadIdentityUser`, scoped to that repo's `attribute.repository`) —
this is real GCP IAM setup outside GitHub Actions, not something this workflow can do for
you. `--allow-unauthenticated` is always applied: the real access boundary for services in
this portfolio is app-level (a JWT, a signed request), not GCP IAM, since callers have no GCP
identity to present.

**Env vars go through `env-vars-json`, not `deploy-cloudrun`'s own `env_vars` input.** That
input parses commas as entry separators between `KEY=VALUE` pairs, silently corrupting any
value containing a comma (e.g. a comma-separated origins list) unless pre-escaped.
`env-vars-json` is written to a file and passed via `--env-vars-file` instead, sidestepping
the bug. Build it straight from `vars.*` — `secrets.*` can't go in a `with:` block anyway, and
if a value isn't actually sensitive (most deploy-time config isn't — model names, numeric
caps, a public URL, an allowed-origins list), it shouldn't be a secret in the first place.
Real secrets belong in GCP Secret Manager, referenced by name (never value) via
`gcp-secrets-json: {"CONTAINER_ENV_VAR": "SECRET_NAME:latest"}`.

Other inputs: `dockerfile` (default `"Dockerfile"`, relative to `source-path`),
`runtime-service-account` (empty uses the project default compute SA),
`min-instances`/`max-instances` (default `0`/`2`), `artifact-keep-count` (default `5`),
`extra-flags` (raw passthrough for anything not covered). Output: `url`.

### `deploy-cloudflare-pages.yml`

Build + deploy to Cloudflare Pages, symmetric to `deploy-github-pages.yml` — same shape
(`build-command`/`dist-path`/`node-version-file`, generic `build-secret-1/2/3` passthrough,
a `working-directory` input for a monorepo-style frontend), with the publish step and auth
model swapped for Cloudflare's own (an API token + account ID, not GitHub's Pages OIDC).
Kept as its own reusable workflow rather than merged into `deploy-github-pages.yml` behind a
host switch — the two hosts need different actions and credential models entirely, so one
file per host stays simpler than one file branching on which host.

```yaml
jobs:
  deploy:
    permissions:
      contents: read
      deployments: write
    uses: danibsheehan/dani-actions/.github/workflows/deploy-cloudflare-pages.yml@v13
    with:
      build-command: npm run build
      dist-path: dist
      working-directory: frontend
      project-name: ${{ vars.CLOUDFLARE_PAGES_PROJECT_NAME }}
      site-public-url: ${{ vars.SITE_PUBLIC_URL }} # optional soft check, never fails
    secrets:
      cloudflare-api-token: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      cloudflare-account-id: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

If a repo's frontend build needs a value from a sibling deploy job (e.g. a freshly-deployed
backend's URL for `VITE_API_BASE`), map it onto `build-secret-1/2/3` the same way
`deploy-github-pages.yml` does — even though it isn't actually secret, reusing the identical
generic-slot mechanism keeps both shared frontend-deploy workflows consistent. See
[File naming conventions](#file-naming-conventions) below for how this interacts with a
repo whose two deploy jobs have a real ordering dependency.

**Old production deployments are pruned automatically** (`production-keep-count`, default
`5`) — Cloudflare never expires a deployment's own hash URL on its own, so without this,
every past production build (including a broken one a bad deploy shipped) stays reachable
forever. Runs only after the smoke check confirms the new deploy is good, and is
deliberately non-fatal (`::warning::`, not a failed step) if the Cloudflare API has a hiccup
— unlike `pages-preview-cleanup.yml` (whose only job is cleanup), this is a secondary concern
bolted onto a deploy job whose primary purpose already succeeded.

## Testing

The Python scripts behind `check-cobertura-threshold`, `merge-cobertura-by-file`, and
`pr-guide-engine` have a pytest suite in `tests/`, run from the repo root:

```
pip install -r requirements-dev.txt
pytest
```

CI (`.github/workflows/verify.yml`) runs this suite on every PR and push to `main`, plus
[`actionlint`](https://github.com/rhysd/actionlint) against every workflow and composite
`action.yml` in the repo.

## File naming conventions

Every consuming repo should name its workflow files by what they do, not by a generic
umbrella term — `ci.yml`/`test.yml` doesn't say whether it lints, tests, deploys, or all
three. Same target/purpose = same filename across every repo that has it:

- **`verify.yml`** — the parallel PR/push verification jobs (calls `npm-verify.yml`)
- **`deploy-pages.yml`** — GitHub Pages deploys (calls `deploy-github-pages.yml`)
- **`deploy-cloud-run.yml`** — Cloud Run deploys (calls `deploy-cloud-run.yml`)
- **`deploy-cloudflare-pages.yml`** — Cloudflare Pages deploys (calls `deploy-cloudflare-pages.yml`)
- **`codeql.yml`** — CodeQL scanning (calls `codeql-js.yml` for JS/TS-only repos; bespoke
  for multi-language repos)
- **`dependency-review.yml`** — calls the reusable workflow of the same name
- **`pr-guide.yml`** — calls the reusable workflow of the same name
- **`lighthouse.yml`** — calls `lighthouse-ci.yml`
- **`weekly-probe-smoke.yml`** — calls `health-probe.yml` (only relevant to a repo with a
  deployed backend of its own to probe)
- **`verify.yml`**'s Go jobs — calls `go-verify.yml` (only relevant to a repo with a Go
  module; job id/name conventions stay caller-chosen, e.g. caught-looking's `backend`)
- **`dependabot-auto-merge.yml`**, **`pr-labels.yml`** — already-standardized
  single-purpose workflows

A repo with two *independent* deploy targets (e.g. a Pages-hosted app plus a
Cloud-Run-hosted service with no ordering dependency between them, like musing's
`musing-ai-service`) gets separate files per target — never a single `deploy.yml` covering
both, since "what does this deploy, and where" should be answerable from the filename alone.

**Exception**: when one deploy target's build genuinely depends on another's output from the
*same* run (e.g. a frontend build that needs the backend's just-deployed URL baked in as
`VITE_API_BASE` — GitHub Actions' `needs:` only works between jobs in the same workflow
file, not across separately-triggered files), keep both as jobs in one caller file instead of
splitting them, with the dependent job's `needs:` expressing the real ordering. caught-looking's
`deploy.yml` is the documented instance of this: one file, two jobs (`backend` calling
`deploy-cloud-run.yml`, `frontend` needing `backend` and calling
`deploy-cloudflare-pages.yml`) — both deploy *mechanisms* are still fully generalized into
dani-actions, only the caller-side orchestration stays combined.
