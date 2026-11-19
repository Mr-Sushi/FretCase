# Rules for coding agents

These rules apply to every agent working in this repository, human-directed or parallel.

## Before you start

1. Read `docs/architecture.md`, then the interface files in `shared/schema/` and `docs/api.md`.
2. Work only inside the directory you were assigned (`engine/` + `server/`, `app/`, or `device/`). If you need something from another directory, use the interface; do not read or edit its implementation.
3. If an interface is missing something you need, stop and say so. Do not invent fields or messages on your side.

## While you work

- Preserve the existing architecture and behaviour. Do not rewrite working code for style.
- Do not add features nobody asked for.
- Code ported from FretStudio (see `docs/porting-from-fretstudio.md`) keeps its tests, and they must keep passing. Do not refactor ported code in the same change that ports it.
- Every network call has a timeout and an offline fallback. The full flow must run with no network.
- Keep secrets out of the repository. API keys come from environment variables.

## Before you hand back

- Run the tests for your directory and report the numbers.
- List any change you made to a shared interface, and why.
- Code, comments and commit messages in English. Design documents in `docs/` may be in Chinese.
