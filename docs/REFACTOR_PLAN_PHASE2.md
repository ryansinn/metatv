# MetaTV — Refactor Plan, Phase 2 (post-PR #1 review follow-ups)

Carries forward from **[REFACTOR_PLAN.md](REFACTOR_PLAN.md)**. Bands P0 and P1 of the
original plan landed in PR #1 (`refactor/p0-correctness-bugs`, 2026-06-01). This document
captures **new follow-ups surfaced during the PR #1 code review** plus a pointer to the
original bands that are still open.

Same ground rules as the original plan apply: one task per commit, characterization test
before any behavior-preserving refactor, `venv/bin/python -m pytest tests/ -q` green after
each task.

---

## Priority 0 — Review follow-ups (latent correctness)

### F0-1 — `_apply_favorite_toggle` reads ORM attributes after `session.close()`
- **Where:** `metatv/gui/main_window.py` — `_apply_favorite_toggle` (~line 660). After the
  `finally: session.close()`, the code reads `channel.name` / `channel.is_favorite` for the
  status-bar message; `toggle_favorite_by_id` then passes the same detached `channel` into
  `update_details_pane_for_channel`, which reads `channel.media_type` / `channel.provider_id`.
- **Why it's a problem:** the sessionmaker uses the default `expire_on_commit=True`, and
  `ChannelRepository.toggle_favorite` commits — so every column on `channel` is expired by the
  time the session closes. It currently works **only by accident**: `toggle_favorite`'s own
  `logger.info(f"...{channel.name}...")` (`repositories/channel.py:366`) touches an expired
  attribute while the session is still open, which makes SQLAlchemy refresh the *entire* row.
  Remove or change that log line and the post-close reads become `DetachedInstanceError`.
  Verified empirically during review.
- **Fix:** read everything needed into locals *inside* the `try` block before `session.close()`:
  ```python
      new_status = repos.channels.toggle_favorite(channel_id)
      channel.is_favorite = new_status
      name = channel.name
  finally:
      session.close()
  status = "added to" if new_status else "removed from"
  self.status_bar.showMessage(f"{name} {status} favorites")
  ```
  For `toggle_favorite_by_id`, either pass `channel_id` (re-fetch in `update_details_pane_for_channel`,
  which already opens its own session) or expunge/refresh the instance before close so it is
  not relying on the repo's logging side-effect.
- **Accept:** no ORM attribute is read after its session closes; behavior unchanged; a test
  pins the status message and details-pane refresh with the repo log line removed/neutralized
  (so the accidental-refresh crutch can't mask a regression).

---

## Priority 3 — View-owned executors not shut down on exit
*(extends original-plan P3; same leak class P0-3 targeted, scoped out of PR #1)*

### F3-1 — `PreferencesView._executor` and `DiscoverView` thread leak on app close
- **Where:** `metatv/gui/preferences_view.py` (`self._executor = ThreadPoolExecutor(max_workers=1)`
  in `__init__`) and `metatv/gui/discover_view.py` (background loader thread). PR #1 added
  `on_deactivate()` to both, but `MainWindow.closeEvent` does **not** call `on_deactivate()` on
  whichever view is currently visible, and neither executor/thread is shut down in `closeEvent`.
- **Why:** mirrors P0-3 (closeEvent must stop every owned pool/thread). Low severity — one
  `max_workers=1` pool each and the process is exiting — but it's the same rule.
- **Fix (pick one):**
  - have `closeEvent` call `on_deactivate()` on the active content view before teardown, and
    add an explicit `_executor.shutdown(wait=False)` in `PreferencesView`'s deactivate/cleanup; or
  - give each view a `cleanup()` and call them all from `closeEvent` alongside the managers.
- **Accept:** closing the app while Discover or Preferences is the active view leaves no live
  worker thread; tests assert the shutdown path.

---

## Priority 4 — Nits / hygiene (opportunistic)

### F4-1 — Drop the dead `config=None` arrow fallbacks
- **Where:** `metatv/gui/filter_panel.py` and `metatv/gui/global_filter_dialog.py` — every
  toggle keeps `config.<icon> if config else "▶"/"▼"`. All production call sites now pass
  `config=self.config` (PR #1), so the literal branches are dead and technically still violate
  the "no hardcoded icon literals" rule.
- **Fix:** make `config` a required constructor arg in those private widget classes (drop the
  `=None` default), delete the `else "▶"/"▼"` branches. The icon registry stays the single
  source of truth.
- **Accept:** no `"▶"`/`"▼"` literal remains in either file; all callers already pass config so
  no signature break in practice; tests pass.

### F4-2 — Update stale `time_slot` comment in `get_schedule`
- **Where:** `metatv/core/repositories/epg.py:178` — comment reads "local approximation — EPG is
  UTC but close enough."
- **Why:** after the P0-2 fix, `day_start` is anchored to local-midnight-expressed-in-UTC, so the
  slot windows are now **exact** local-time windows, not an approximation. The comment is now
  misleading.
- **Fix:** reword to note the slot bounds are exact local-time offsets from the converted
  `day_start`. Pure comment change.
- **Accept:** comment matches behavior; no code change needed.

---

## Still open from the original plan

These were never part of PR #1 (which covered P0 + P1 only):

- **P2** — inline stylesheets → `theme.py` (`epg_view.py` ~63, `provider_editor.py` ~36,
  `global_filter_dialog.py` ~30). See REFACTOR_PLAN.md §Priority 2.
- **P3** — decompose oversized files >1000 lines (`main_window.py` ~4178, `epg_view.py` ~2167,
  `sidebar_sections.py` ~1403, `provider_editor.py` ~1120, `filter_panel.py` ~1061).
  See REFACTOR_PLAN.md §Priority 3.
- **P4** — status-set dedup (5 sites, refactor-audit memory) + delete stray 25 MB `--help`
  artifact. See REFACTOR_PLAN.md §Priority 4.
- **Test bands T2/T3** — core-engine coverage gaps and pytest-qt widget/integration tests.
  See REFACTOR_PLAN.md §T2/§T3.
