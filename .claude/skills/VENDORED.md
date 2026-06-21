# Vendored skills — superpowers

These agent skills are **vendored** (source copied into this repo), not installed as a
Claude Code plugin. Claude Code auto-discovers skills under `.claude/skills/`, so they are
active for anyone working in this repository.

## Origin
- **Project:** superpowers — https://github.com/obra/superpowers
- **Author:** Jesse Vincent (obra)
- **License:** MIT (see `LICENSE.superpowers` in this directory)
- **Vendored commit:** `896224c4b1879920ab573417e68fd51d2ccc9072`
- **Vendored on:** 2026-06-19

## What was copied
- `skills/*` → `.claude/skills/*` (14 skills, this directory)
- `hooks/*` → `.claude/superpowers-hooks/` (session-start auto-activation hooks; **not wired
  into `settings.json` yet** — optional, see below)

## The 14 skills
brainstorming · dispatching-parallel-agents · executing-plans ·
finishing-a-development-branch · receiving-code-review · requesting-code-review ·
subagent-driven-development · systematic-debugging · test-driven-development ·
using-git-worktrees · using-superpowers · verification-before-completion ·
writing-plans · writing-skills

## Optional: auto-activation hook
Upstream uses a `session-start` hook (`.claude/superpowers-hooks/`) to inject the
"using-superpowers" guidance at the start of every session. We did **not** add it to
`settings.json` to keep the change minimal and reversible. To enable it, register the hook
in `.claude/settings.json` (or `settings.local.json`) per upstream `hooks/hooks.json`.

## Updating
Re-clone upstream and re-copy `skills/`, then bump the *Vendored commit* hash above:
```
git clone --depth 1 https://github.com/obra/superpowers.git
cp -r superpowers/skills/* .claude/skills/
```
