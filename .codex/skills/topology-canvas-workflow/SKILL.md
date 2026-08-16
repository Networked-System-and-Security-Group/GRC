---
name: topology-canvas-workflow
description: Build, tune, catalog, and render topology canvas files for switch-only link-state visualization in this repository. Use when Codex needs to create or reuse a canvas JSON for a topology, generate static black-line outline PNGs for layout tuning, or render directed-link GIFs from `analysis.deep_analyse` / `link_states`. This skill is specifically for workflows centered on `analysis/canvases/`, `analysis/canvas_link_gif.py`, and experiment reports or assets that depend on topology-aware canvas rendering.
---

# Topology Canvas Workflow

## Overview

Use this skill to keep all topology canvas work on one path:

1. Check whether a matching canvas already exists.
2. If not, create a new canvas under `analysis/canvases/`.
3. Generate a static outline PNG and inspect it before any GIF rendering.
4. Adjust the canvas until the static topology layout is acceptable.
5. Only then render link-state GIFs.

## Workflow

### 1. Check the existing canvas catalog first

Before creating or editing any canvas, read:

- `analysis/canvases/catalog.txt`

The catalog format is intentionally patch-friendly:

- line 1: canvas file
- line 2: description
- line 3: topology file

Match on:

- topology file
- description of the intended observation region

If an existing canvas already fits, reuse it instead of creating a new one.

Do not create a duplicate canvas just because the experiment ID changed. Canvases are topology/layout assets, not per-experiment assets.

### 2. Use the canonical canvas locations

Store reusable topology canvas assets only here:

- canvas JSON: `analysis/canvases/*.json`
- outline PNG: `analysis/canvases/outlines/*.png`
- catalog: `analysis/canvases/catalog.txt`
- topology-specific generators: `analysis/canvases/*.py`

Do not store canonical canvas JSON files under experiment directories.

This repository currently keeps only one canonical reusable canvas in `analysis/canvases/`:

- `ft-full-switches.json`

If you need a temporary local view, put it under the experiment directory first. Promote it into `analysis/canvases/` only after it proves reusable.

Experiment directories may contain:

- run scripts
- reports
- generated GIFs
- experiment-specific snapshots or comparisons

### 3. Create a new canvas only when the catalog has no match

When a new topology or new observation scope is needed:

1. Decide whether a generator script is justified.
2. If the layout is topology-wide and systematic, prefer a generator script under `analysis/canvases/`.
3. If the layout is a small one-off local view, a hand-authored JSON is acceptable.
4. If it becomes canonical, add a three-line entry to `analysis/canvases/catalog.txt`.

Keep canvas JSON explicit:

- node set
- node positions
- edge set
- style overrides when needed

For topology-wide layouts, choose figure width/height from the topology bounds and cap width:height at `2.5:1`.

### 4. Generate a static outline PNG before any GIF rendering

This step is mandatory for new canvases and recommended for reused canvases after any layout edit.

Use:

```bash
python3 analysis/canvas_link_gif.py \
  --canvas analysis/canvases/<canvas>.json \
  --outline-png analysis/canvases/outlines/<canvas>.png
```

Inspect the outline image before rendering GIFs.

If the outline is poor:

- adjust coordinates
- adjust figure width/height
- adjust line width
- adjust bounds padding
- regenerate the outline

Do not proceed to GIF rendering until the static topology image is acceptable.

### 5. Render GIFs only after the outline is acceptable

Use:

```bash
python3 analysis/canvas_link_gif.py \
  --config-id <exp_id> \
  --canvas analysis/canvases/<canvas>.json \
  --metrics utilization,qlen \
  --every-n 10 \
  --fps 6 \
  --out-dir <output-dir>
```

Use `analysis.deep_analyse`-compatible experiments only.

When rendering multiple GIFs in one batch, estimate timeout from the GIF count:

- assume `1 GIF ~= 1 minute`
- `gif_count = experiment_count x metric_count`
- set the shell timeout for that batch to at least `gif_count` minutes
- prefer adding a small buffer, e.g. `gif_count + 2` minutes

Do not keep polling short windows while a batch is still within that timeout budget.

### 6. Reuse the existing renderer unless there is a clear gap

Prefer extending:

- `analysis/canvas_link_gif.py`

instead of creating parallel renderers.

If behavior changes affect the workflow contract, update:

- `analysis/canvases/catalog.txt`
- the relevant experiment report
- `docs/Code_Change_Log.zh-CN.md`
- `docs/Experiment_Iteration_Log.zh-CN.md` when the change produces a new experiment artifact set

## Quick Checklist

Before finishing canvas work, confirm all of the following:

- Catalog checked first
- Canvas JSON lives under `analysis/canvases/`
- Outline PNG generated under `analysis/canvases/outlines/`
- Outline reviewed and tuned before GIF rendering
- New canonical canvas added to `analysis/canvases/catalog.txt` if applicable
- Batch timeout budget computed from `1 GIF ~= 1 minute` when rendering multiple GIFs
- GIF outputs stored under an experiment directory, not under `analysis/canvases/`
