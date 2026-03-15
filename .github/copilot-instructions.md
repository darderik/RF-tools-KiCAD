# RF-Tools KiCad – Copilot Instructions

## Project shape (what matters first)
- This repo is a **bundle of pcbnew Action Plugins + footprint wizards**, loaded by KiCad through package imports.
- Top-level loader is `__init__.py`; each plugin subpackage registers itself in its own `__init__.py` (example: `via_fence_generator/__init__.py`).
- Main plugin dirs: `round_tracks/`, `taper_fz/`, `trace_solder_expander/`, `tracks_length/`, `trace_clearance/`, `via_fence_generator/`, `rf_tools_wizards/`.
- `packaging/` is generated release content; source-of-truth is the top-level plugin folders.

## Core implementation pattern
- Action plugins subclass `pcbnew.ActionPlugin`, define `defaults()`, and implement `Run()` (see `round_tracks/round_trk.py`, `trace_clearance/trace_clearance.py`, `via_fence_generator/viafence_action.py`).
- Dialogs are wxFormBuilder-generated base classes (`*_basedialogs.py` / `*Dlg.py`) wrapped by derived classes (`viafence_dialogs.py`, etc.).
- Persisted user settings live in per-plugin INI files (for example `via_fence_generator/vf_config.ini`, `trace_clearance/tc_config.ini`). When adding UI fields, update both load and save paths.

## Version-compatibility rules (KiCad 5.1–8.0+)
- Keep `hasattr`-based API shims; do not collapse them.
- Common forks to preserve: `TRACK` vs `PCB_TRACK`, `ZONE_CONTAINER` vs `ZONE`, `VIA` vs `PCB_VIA`, `wxPoint`/`VECTOR2I` handling.
- Geometry and board operations should remain in pcbnew internal units; convert only at UI boundaries with `pcbnew.FromMM` / `pcbnew.ToMM` (or local `ToUnits`/`FromUnits` aliases).

## Via Fence architecture (cross-file flow)
- UI/config in `via_fence_generator/viafence_dialogs.py` + `vf_config.ini`.
- Plugin orchestration in `via_fence_generator/viafence_action.py` (track selection, arc discretization, filtering, via creation).
- Geometry engine in `via_fence_generator/viafence.py` (`generateViaFence`, `generateViaFenceMultiRow`, path interpolation helpers).
- Current multi-row controls are `fence_rows_per_side` and `inter_row_offset` (UI: `spnFenceRows`, `txtInterRowOffset`), with half-pitch brick shift on odd rows.
- Keep deduplication/filtering order intact: generate points → de-dup → optional clearance checks → precise overlap pass.

## Build, packaging, and test workflows
- Package release artifacts with `python package.py` from repo root.
- `package.py` copies declared plugin folders/files into `packaging/` and creates `rftools.zip` from **packaging contents**.
- If adding/removing plugins, update `plugins_folders` (and any copied resources/files) in `package.py` and imports in top-level `__init__.py`.
- Via-fence regression harness: `python -m via_fence_generator --runtests`.
- Inspect/update one fixture: `python -m via_fence_generator --test simple-test --verbose` and optionally `--store`.

## Repo-specific conventions to keep
- Preserve GPL headers in existing source files.
- Prefer small geometry helpers over inlined math in plugin `Run()` methods.
- Use `wx.LogMessage`/local debug helpers instead of ad-hoc prints inside KiCad plugin flow.
- Do not edit `packaging/plugins/*` directly for feature work; mirror changes from source dirs and re-run packaging.