# Repository Instructions

## Versioning

- Treat `pyproject.toml` and `src/dockwatch/__init__.py` as the authoritative version sources. Keep them in sync.
- This project is pre-1.0. Follow strict pre-1.0 semantic versioning:
  - `0.X.0` minor bump: any new feature, new page/panel, significant UI restructuring, new integration, new command, or other user-visible capability change.
  - `0.x.Y` patch bump: bug fixes, small UX polish, copy updates, docs, tests, or internal refactors that do not add user-visible capability.
- If even one change in a release is minor-level, bump the minor version and reset patch to `0`.
- Do not leave the version unchanged after shipping meaningful feature work.

## Release Hygiene

- Before committing a release-oriented change set, classify the included work as feature-level or fix-level.
- When a version bump is needed, update every authoritative version location in the same commit.
- Do not change unrelated docs or examples just to mirror the version unless they are part of the release surface.
