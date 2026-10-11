# Repository workflow

## Commit and push substantial changes

- When a task produces substantial, complete repository changes, verify the work, review the diff, create a focused commit with a meaningful Conventional Commit message, and push the current branch to its configured upstream before handing off.
- Substantial changes include working application code, tests, API or data-model changes, build or deployment configuration, and documentation that materially changes project behavior or direction.
- Do not create a commit for trivial formatting, typo-only edits, temporary debugging, empty scaffolding by itself, or unfinished/broken work.
- Stage only changes that belong to the completed task. Preserve unrelated user changes and never commit secrets, local environment files, credentials, generated artifacts, or large data/model files.
- Run the relevant available tests, lint, type checks, or build checks before committing. If verification, authentication, networking, or branch protection prevents a safe push, leave the changes intact and report the exact blocker.
- Use a concise message that explains the outcome, such as `feat: add group settlement workflow` or `docs: define ResFinance implementation plan`.
- Never amend an existing commit, force-push, rewrite history, or bypass repository protections unless the user explicitly asks.
