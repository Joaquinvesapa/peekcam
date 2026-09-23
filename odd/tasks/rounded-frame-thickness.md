# Rounded frame thickness

## Goal
Make the Rosé Pine frame a continuous rounded band, twice its previous 1.5px visible core thickness.

## Scope
- Draw a 3px inner-contained border that follows rectangle, rounded rectangle, and circle outlines.
- Preserve the subtle matching inner shadow, camera mask, snapshot, recording marker, and unrelated working-tree changes.
- Add offscreen corner and thickness regression checks.

## Tasks
- [x] Add exact-pixel offscreen assertions for 3px thickness and four-corner coverage (rectangle, rounded rectangle, circle). Route: delegated writer; new test failed for all three shapes before change.
- [x] Fill a continuous 3px band between outer and inset contours, retain inner shadow, and verify without disturbing unrelated edits. Five focused tests passed; independent verification repeated tests, compileall and diff check. Parent spot check repeated focused tests.

## Verification
TDD not configured; ordinary tests (writer observed RED and GREEN). Runner: `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p 'test_overlay_frame.py' -v`. Assessment was unassessable due to existing untracked paths, so an independent verifier checked the change. Nontransparent optional configured borders were not visually verified and can overlay this ring; they are unchanged by this task.

## Delivery
Forecast under 100 authored diff lines; strategy ask-on-risk. No commit without explicit authorization, particularly with unrelated dirty changes. Engram mirror unavailable (no callable memory tools).
