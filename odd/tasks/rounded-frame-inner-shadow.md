# Rounded frame inner shadow

## Goal
Complete the Rosé Pine frame around rounded corners and add a subtle same-color inner shadow without changing the camera pixels away from the edge.

## Scope
- Adjust frame geometry to follow the masked rectangle, rounded rectangle, and circle contours.
- Add a restrained inner shadow and offscreen rendering regression coverage.
- Preserve existing unrelated working-tree changes and configurable border behavior.

## Tasks
- [x] Add focused regression coverage for corner contours, transparency, inner-edge tint, and untouched camera center. Route: delegated writer (two non-trivial files); new shadow assertions failed before the change.
- [x] Reduce inset rounded-corner radius and paint a clipped, translucent Rosé Pine inner shadow. Route: delegated writer; five focused tests passed. Independent verification repeated the tests, compiled both files, and ran `git diff --check`; parent spot check repeated the focused tests.

## Verification
TDD: not configured; ordinary focused checks (the writer also observed RED before implementation and GREEN after). Runner: `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p 'test_overlay_frame.py' -v`. Native assessment was unassessable due to existing untracked paths, so independent verification was used. The verifier noted that the always-on Omarchy decoration ignores `border_width=0` and transparent `border_color`; this is existing intended behavior, not introduced by this task. Configured border is still drawn afterward.

## Delivery
Forecast: under 100 authored diff lines. Strategy: ask-on-risk. No commit: repository has unrelated uncommitted changes and this session has no explicit user authorization to commit. Engram mirror unavailable (no callable memory tools).
