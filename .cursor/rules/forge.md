# .continue/rules/forge.md

- docs/forge-context.md is the canonical project context and source of truth.
- Before making code suggestions or architectural decisions, prefer the guidance in docs/forge-context.md over assumptions.
- In Agent mode, read docs/forge-context.md before proposing non-trivial changes.
- Preserve the existing Forge architecture, milestone model, and state transition design unless the user explicitly asks to change them.
- Prefer minimal, targeted edits over broad rewrites.
- When the repo state or diff conflicts with docs/forge-context.md, call out the mismatch explicitly.