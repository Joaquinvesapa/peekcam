# Monitor layout recovery

## Objective
Keep PeekCam reachable after startup and monitor-layout changes, including Ctrl+Shift+F12 translating DP-2 between x=2560 and x=0.

## Scope and constraints
- App-owned Qt geometry recovery; no shortcut or Hyprland configuration edits.
- Preserve monitor-relative placement on surviving outputs; use a visible output when the previous one disappears.
- Preserve valid negative coordinates, hidden state, click-through and normal user placement. Normalize against individual available screen rectangles, not a bounding union. Recover unreachable geometry; maintain visibility without forcing every partially clipped window fully inside.
- Validate malformed saved geometry, handle oversized windows, defer empty/transient screen sets, coalesce layout events.
- Record corrected geometry in configuration and sample current geometry on quit.
- Preserve existing dirty README.md, run.sh, install.sh, .gitignore and unrelated untracked files.
- Branch: fix/monitor-layout-recovery; base b99ab00599352b385db400de13d25af359acdb73.
- User authorized implementation, not commits/push/PR. Work-unit commits remain pending explicit Git authorization; do not mark a task closed without it.

## Delivery and routing
Delivery strategy: single-pr (user-chosen after oversized-delivery menu; whole feature in one PR, 824 authored lines, ~550 tests). Initial forecast was 380 lines; initial integrated scope was 585 additions plus 7 deletions; final independently measured scope is 817 additions plus 7 deletions (824 authored lines) excluding this tracking file. Delivery exceeds advisory review size; ordered chaining/single-PR choice is required before any work-unit commit. No commits currently authorized.
Single writer per task, delegated to gentle-ai-worker (multi-file/preparation trigger). Independent verification follows native ASSESS and applicable functional checks. RDD mode currently on; inspect normalized candidate through provider facade before completion. No review authority grants Git delivery.

## Tasks
- [x] T1 — Normalize restored geometry against current screens, with deterministic regression tests. Status: implemented; independent verification and commit pending. Route: delegated writer (mur1nubh-4-yjl4). Commit: 04511a4 (shared single work-unit commit).
- [x] T2 — Recover live monitor translations/removal, persist corrected geometry, and verify layout toggling. Status: done. Live-validated for startup and Ctrl+Shift+F12 both directions; known gap accepted by user: quit under dual layout saves stale geometry (placement fidelity only). Route: delegated writer (mur1tj6c-5-dkvc) and independent verifier (mur2104c-6-pd9d), then bounded correction writer. Commit: 04511a4.

## Acceptance and verification
- RED/GREEN deterministic tests for stale x=4716 on 2560-wide output, valid secondary/negative origins, gaps, malformed/oversized geometry and no-screen handling.
- Live events cover screen added/removed/primary and geometry/work-area changes, coalescing; hidden overlay is not shown automatically.
- Surviving monitor translation retains relative offset; removed monitor falls back deterministically.
- Corrected geometry persists; closing/reopening does not restore unreachable coordinates.
- Focused and full Python test suite, diff checks, and real XWayland Ctrl+Shift+F12 validation. Live disruptive actions/restart need explicit permission; do not infer Qt signal behavior from tests.

## Progress and evidence
Existing window manually shown and moved successfully; user confirmed it is visible. This does not validate permanent prevention.
T1 worker reported actual RED assertion: restored x=4716 instead of expected x=2184; then GREEN with 12 focused tests and 38 full-suite tests passed; git diff --check passed. Approximate T1 change 225 lines. New helper in peekcam/geometry.py; startup integration in overlay_window.py; tests/test_overlay_geometry.py. Empty screens defer; accessibility requires up to 32px on both axes of one screen.
Native ASSESS could not assess because untracked scope is undeclared: risk unassessable, independent verifier required. No native review closure exists. Independent verifier will check integrated candidate after T2; explicit intended-untracked scope must be resolved before review.

T2 observed RED: x=4600 instead of x=2040 after translation and zero startup save calls; after fix 11 live-layout tests, 12 startup tests and full 49-test suite passed; diff check passed. Added coalesced app/per-screen hooks, value-based screen snapshots, deferred empty layouts, corrective persistence, quit geometry readback. Independent verifier running; live signal delivery not proven.
Native INSPECT selected only new geometry/tests as intended-untracked and returned ready, but current workspace projection also includes preexisting .gitignore/README/install/run changes. No START issued to avoid freezing unrelated changes as the feature candidate. Native review requires candidate isolation before closure; no lineage exists.

Independent verifier observed 12 startup, 11 monitor-layout and 49 full-suite tests pass, and tracked diff check pass. It identified two causal blockers not covered: old monitor rectangles can misidentify a compositor-already-repositioned window and double-translate it (swap DP-2/DP-3 origins, compositor x4600→2040, application incorrectly moves back to4600); startup Config.save filesystem failures propagate and abort construction. Findings are structural; correction writer must reproduce actual assertions before fixing. Zero-delay coalescing does not establish multi-turn topology stability. No test proves live XWayland delivery.

Correction writer (mur24x9r-7-a9ex) observed RED in both compositor orderings (4600 != 2040), live PermissionError/OSError and four startup save-error cases. Added durable placement evidence/QWindow identity to avoid double translation, narrow OSError logging to preserve recovered window while save fails. Focused monitor suite 17 passed, startup suite 13 passed, full suite 56 passed, diff check passed. ValueError remains unsuppressed. Failed saves cannot guarantee disk persistence. Targeted independent verifier (mur2bqm7-8-ml6j) running.

Targeted verifier independently confirmed 13 startup/17 layout/full56 pass and save-error blocker resolved. Related conditional identity timing remains: after compositor moves4600→2040, transient QWindow identity DP-3 overrides durable DP-2 ownership, potentially shifting back4600. Structural finding only; parent spotchecked override code. Add executed transient-identity regression and narrowly fix ownership precedence during topology change; no broader review expansion.

Transient-identity writer mur2emej-9-rui1 executed RED for both compositor orderings (4600 versus2040), missing ownership and duplicate ownership. Correction preserves durable ownership during topology change and requires unique translation ownership; four new regressions passed along with user-drag behavior and idempotence. Worker observed 21 layout,13 startup and full60 tests passed plus diff check. Reported571 lines only cover latest allowed surfaces, not full feature. Final narrow verifier mur2hql2-a-q8zl running regressions/full suite and whole-feature size recount; no broad new review cycle.

Final verifier mur2hql2-a-q8zl independently observed21 topology and full60 tests passed and diff check passed. All four requested transient-identity/ambiguous-ownership regressions executed in both suites. Covered ownership defects resolved. Feature size817 added7 deleted=824 lines including geometry helper and both untracked tests; earlier571 was partial-surface count. No app restart, monitor changes, native review START or Git delivery performed.

Live validation (user-authorized, parent-run on real Hyprland/XWayland, single DP-2 baseline, config backed up at /tmp/peekcam-config.before.json): (1) Forced stale saved geometry [4716,1183,376,212], restarted candidate: window opened at [2184,1183] and config persisted [2184,1183]. (2) toggle-monitor-layout single->dual: window followed DP-2 to [4744,1183] (2184+2560); dual->single: back to [2184,1183]; stable at +1s and +4s, no double shift, empty stderr log. (3) Quit under dual layout (window actually at [4744,1183]) saved config [2184,1183,...] instead of actual; layout toggled while closed; reopen placed window at [2184,1183], reachable. Finding: quit geometry readback did not capture the compositor-moved position, suggesting Qt geometry() is stale for compositor-driven moves under XWayland; impact is placement fidelity on reopen in dual (may open on the other monitor), not unreachability. Not fixed; hidden/click-through and monitor-removal not exercised live (covered only by offscreen tests). Final state: single-monitor layout restored, candidate PeekCam running (PID varies).

## Next step
User decision: fix quit-time geometry fidelity (needs actual-position source under XWayland, e.g. compositor query or tracked placement evidence) or accept. Native review remains pending isolated candidate; review workload (824 lines) strategy selection required before commits.

## Closure
User accepted the quit-geometry gap and authorized commit and push (PR not requested). Commit 04511a4 `fix(overlay): keep window reachable across monitor layout changes` holds 817 additions and 7 deletions across geometry helper, overlay window, main and two test files; 60 tests passed as spot check before commit. Native ASSESS stayed unassessable because unrelated untracked files exist, so no native review ran; independent verifiers covered the candidate. Pre-existing dirty README, run.sh, install.sh and .gitignore were left unstaged.
