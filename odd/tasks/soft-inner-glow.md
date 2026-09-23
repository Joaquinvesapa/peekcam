# Soft inner glow

## Goal
Make the existing Rosé Pine inner shading visibly fade from the 3 px frame into the camera, without thickening the core or tinting the center.

## Scope
- Adjust only overlay painting and focused offscreen rendering tests.
- Preserve the current rounded, rectangular and circular frame geometry, snapshots, recording indicator and unrelated working-tree changes.

## Tasks
- [x] Add graded inner-glow rendering assertions and implement the restrained fade. Route: delegated writer (two non-trivial files). Five focused offscreen tests and `git diff --check` passed; no strict TDD mode configured.
- [x] Independently verify focused rendering and inspect the final diff. Route: delegated verifier after native assessment was unassessable. Independent verification passed 5 tests and diff check; parent repeated the 5 focused tests.

## Verification
TDD not configured (prior feature task evidence); use ordinary focused checks. Runner: `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p 'test_overlay_frame.py' -v`. Writer observed 5 passing tests and clean diff check. Native assessment unassessable due to pre-existing untracked files; independent verifier repeated both checks successfully and parent repeated the focused tests. Tests sample one inward ray per shape, not the whole perimeter. Independent check passed; parent repeated five tests after tightening the fade. Native assessment remained unassessable with pre-existing untracked files. Native inspect with untracked files excluded returned `managed_assets_outdated`; no candidate-specific review was started. The full visual appearance has not been observed by the automated tests, but the user confirmed it manually.

## Delivery
Forecast: under 100 authored diff lines. Strategy: ask-on-risk. User authorized commit and push. Code-and-tests work-unit commit: `52e0525a5bc48e6b89293e5ec31e23166835034d` (`feat(overlay): add tighter inner frame glow`). Unrelated worktree changes were excluded. Engram mirror unavailable (no callable memory tools).
