# Exploded Assembly Studio

A Blender add-on that turns an assembled model into an **exploded view** and builds the animation
both ways — explode and assemble — with an optional camera move. It is aimed at product
visualisation for electronics and mechanical hardware: PCBs and enclosures, housings, gearboxes,
network gear, anything that comes apart into layers.

**Version 1.1.0** · tested on **Blender 5.1.2** · minimum **Blender 4.2** (extension install) or
**Blender 3.0** (legacy add-on install)

```text
Assembled model  →  Explode animation  →  Exploded view  →  Assemble animation  →  Assembled model
```

---

## Table of contents

- [What it does](#what-it-does)
- [Install](#install)
- [Quick start: a PCB product](#quick-start-a-pcb-product)
- [Try it without a model](#try-it-without-a-model)
- [Panel reference](#panel-reference)
  - [Source](#source)
  - [Presets](#presets)
  - [Explosion](#explosion)
  - [Rotation](#rotation)
  - [Sequence](#sequence)
  - [Animation](#animation)
  - [Camera](#camera)
  - [Active Part](#active-part)
  - [Filtering](#filtering)
- [How it works](#how-it-works)
- [Rendering](#rendering)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Roadmap](#roadmap)
- [License](#license)

---

## What it does

The typical product is a stack. Components sit on a board, the board sits in a shell, a lid closes
over the top, screws hold it together:

```text
        Screws              ↑ lift away
        Top enclosure       ↑ lifts off
        Components          ↑ lift off the board
   ───  PCB  ───            ● stays put — the reference plane
        Bottom enclosure    ↓ drops away
```

The add-on records where every part sits when assembled, works out where each one should travel to,
and writes real keyframes for the journey. Play it forwards and the product comes apart; play the
assemble pass and it builds itself back into the finished product, landing on exactly the transforms
it started from.

Key points:

- **The assembled state is ground truth.** It is stored per object and restored exactly, so you can
  explode and assemble as many times as you like without the model drifting.
- **It only touches transforms and keyframes.** Never meshes, materials, modifiers or origins.
- **Everything is plain Blender data.** Objects, F-curves, an empty-based camera rig — all of it can
  be hand-edited afterwards. Nothing is locked behind the add-on.
- **Fully undo-compatible.** Every operator registers with Blender's undo stack.

---

## Install

Build the installable zip:

```bash
python build.py
```

That produces `dist/exploded_assembly_studio-1.1.0.zip`.

**Blender 4.2 and newer (recommended)**
`Edit → Preferences → Get Extensions → ▼ → Install from Disk…` and pick the zip.

**Blender 3.0 – 4.1**
`Edit → Preferences → Add-ons → Install…` and pick the zip, then tick the checkbox to enable it.

The panel then lives in:

```text
3D Viewport → press N → "Exploded" tab
```

> Downloading the repository as a zip from GitHub will **not** install directly — Blender expects the
> package folder at the root of the archive. Run `build.py`, or grab the zip from a release.

---

## Quick start: a PCB product

1. Bring the model into Blender with every part sitting where it belongs in the finished product.

2. Select the parts, or set **Source** to `Collection` and pick the collection holding the assembly.

3. **Make the PCB the active object** — click it last, or Ctrl-click it. This one click decides two
   things: the plane the explosion splits around, and what the camera frames.

4. Open **Presets** and click **PCB Product**. That configures:
   - direction `Axis +/- (Split)` on `Z`
   - `Layered` spacing so each stacked layer fans out evenly
   - an explode distance scaled to the actual size of your model
   - a staggered sequence, and the camera set to frame the board

5. Click **Set Assembly Position**. From this moment the current pose is the ground truth.

6. Click **ASSEMBLE** to build the assembly animation (parts start apart and come together), or
   **EXPLODE** for the reverse.

7. Press Play.

Not happy with the spread? Change **Distance** and press the button again. There is no need to undo
anything first — the parts are always measured from the saved assembled state.

---

## Try it without a model

`examples/demo_scene.py` builds a mock PCB product — bottom shell, board, four components, a
connector, a top shell and four screws — so you can see the workflow immediately:

```bash
blender --python examples/demo_scene.py
```

It creates the parts in a `PRODUCT_ASSEMBLY` collection, selects them, and makes the PCB active, so
you can go straight to **PCB Product → Set Assembly Position → ASSEMBLE**.

---

## Panel reference

### Source

| Option | What it does |
|---|---|
| Selected Objects / Collection | Where the parts come from |
| Visible Only | Skip objects hidden in the current view layer |

The header line tells you how many parts were found and how many already have a saved assembly
state, so you can see at a glance whether the add-on is looking at what you think it is.

### Presets

Three starting points. They overwrite the settings below them, so apply a preset first and adjust
afterwards.

| Preset | Look |
|---|---|
| **PCB Product** | Layered vertical build-up around the active object. The intended workflow for boards and enclosures. |
| **Radial Technical** | Even radial spread from the centre, all parts moving together. Clean and diagrammatic. |
| **Product Showcase** | Staggered radial explosion with a spin and a slow orbiting camera. Advertising flavour. |

### Explosion

| Option | What it does |
|---|---|
| **From Center** | Each part moves radially away from the assembly centre. The general-purpose default. |
| **Axis +/- (Split)** | Parts above the centre move along `+Axis`, parts below along `−Axis`. This is the layered-product mode: the board stays, everything above lifts, everything below drops. |
| **World Axis** | Every part moves along the same world axis. |
| **Local Axis** | Each part moves along its own local axis. Useful for directional CAD parts. |
| Distance | Travel distance in scene units. |
| Spacing → Uniform | Every part travels the same distance. |
| Spacing → Proportional | Parts further from the centre travel further. |
| Spacing → **Layered** | Distance is multiplied by the part's layer index, so a stack fans out into even tiers. |
| Center | Reference point: Bounding Box, Median Point, 3D Cursor, or **Active Object**. |
| Layer Tolerance | How close in depth two parts must be to count as the same layer. |
| Use Geometry Center | Measure parts from their bounding-box centre instead of their origin. Turn this off for CAD models whose origins carry meaning. |

**Layer Tolerance** is worth understanding. Without it, four identical capacitors at the same height
would be ranked 1, 2, 3, 4 and fly to four different altitudes. The tolerance clusters parts at
similar depths into one layer so they lift off together as a sheet. It also defines the dead band
around the centre in `Axis +/- (Split)` mode — parts inside it, like the board itself, stay put.

### Rotation

Optional spin applied as a part travels, around a world axis or its own local axis. Small angles
(10–20°) read well in product renders; large ones get busy fast.

### Sequence

Staggered timing, so parts move one after another instead of all at once.

| Option | What it does |
|---|---|
| Order | By distance from centre, position along the axis, name, collection order, or manual |
| Overlap | `0` = strictly one at a time, `1` = everything together |
| Reverse Order | Flip the computed order |
| Mirror Order On Assemble | The assemble pass plays the order backwards, so parts leave outermost-first and return outermost-last |
| Bake Order To Parts | Write the computed order onto the objects and switch to Manual so you can hand-edit it |

### Animation

Start and end frame, interpolation (Bezier, Linear, Sine, Quadratic, Cubic, Exponential, Back,
Elastic) and easing direction. `Back` and `Elastic` give the slight overshoot that reads as
"product advert"; `Sine` with ease-in-out is the safe technical choice.

`Replace Existing` clears the add-on's transform channels before writing new ones, so repeated
clicks never stack up duplicate keys. `Auto Save Assembly State` records the assembled pose for any
part that does not have one yet, so a first-time explode works even if you forget step 5.

### Camera

Three modes.

#### 1. Orbit — automatic, frames the whole exploded model

Builds a small rig you can keep editing by hand:

```text
EAS_Camera_Pivot     empty at the centre — only its Z rotation is keyed
  └── EAS_Camera     parented to the pivot, orbit radius on its local Y
EAS_Camera_Target    empty the camera aims at through a Track To constraint
```

Because the orbit is a single rotation channel, the path is a perfect circle and easing behaves
predictably. `Auto Frame` sets the distance so the whole exploded assembly fits; `Orbit` is how far
around it travels; `Dolly` pushes in or pulls out across the shot.

#### 2. Frame Object — the camera sizes itself to one object

Pick a reference object, normally the PCB, and the camera works out a sensible distance from it.
Click **Use Active Object**, or choose it from the `Frame` field.

The distance comes out of the optics rather than a guess:

```text
subject bounding-sphere radius
        ↓
field of view from focal length and sensor size
        ↓
narrowed to the short side of the render aspect ratio
        ↓
distance = (radius × framing margin) ÷ sin(fov / 2)
```

Which means:

- a bigger board pushes the camera back by exactly the same ratio
- a 100 mm lens instead of 50 mm roughly doubles the distance
- a portrait render pulls back further so the board is not cropped top and bottom
- `Framing Margin` is the only dial you normally need — `1.0` puts the subject edge to edge

The computed distance and the subject size are **shown live in the panel**, in the scene's own
units, so you know what you are going to get before you build anything.

The subject is always measured at its **assembled** pose, so framing stays anchored to where the
part belongs in the finished product even if it flies off during the animation.

#### 3. From Viewport — you hand it the framing

Instead of numbers, capture the first and last camera framing straight from the viewport:

1. Frame the opening shot in the viewport → **Set Start From View**
2. Frame the closing shot → **Set End From View**
3. Build the animation — the camera travels between the two.

Both of these work:

- **From an ordinary user view.** Just orbit the viewport. No camera has to exist yet.
- **From inside the camera preview.** Click `Camera View` (or Numpad 0), turn on `Lock To View`, and
  the viewport moves the camera itself, so what you capture is exactly the render framing. Both
  buttons are in the panel.

Notes:

- The 👁 button next to each pose sends the viewport back to it so you can check or adjust.
- **Focal length is captured too.** Grab the first pose at 35 mm and the last at 85 mm and, with
  `Animate Focal Length` on, the lens blends across the shot.
- Rotation is keyed on the quaternion channel so the camera turns the short way between the two
  orientations instead of unwinding through euler gimbal.
- In this mode the camera has no parent and no aim constraint, so the captured framing is exactly
  what renders. Switching back to Orbit rebuilds the rig.
- The assemble pass mirrors the move, so explode and assemble read as one continuous camera shot.

### Active Part

Per-object overrides for whatever is active:

| Option | What it does |
|---|---|
| Distance Multiplier | Scales this part's travel distance |
| Order | Its place in a manual sequence |
| Exclude From Explosion | Pin the part in place — handy for the board itself |

### Filtering

`Skip Parented Children` decides what happens when a part's parent is also in the assembly. Left on,
only the parent is keyed and the child rides along, which is what you want for CAD hierarchies.
Turned off, every object is animated independently.

---

## How it works

A few decisions worth knowing about if you plan to read or extend the code.

**Local matrices, not world positions.** The assembled state is stored as each object's *basis*
matrix — the local transform that keyframes actually drive. That is why a round trip is lossless:
the test suite reports a return error of `0.000e+00` for unparented parts and about `5e-10` for
parented ones with non-axis-aligned rotation.

**Parent-safe offsets.** Explosion vectors are computed in world space, then converted back into
each object's own parent space before being written. The parent matrix is derived as
`matrix_world @ matrix_basis⁻¹`, which holds for every parent type — object, bone or vertex — so
there is no special-casing.

**Measure before you write.** Object transforms written without a depsgraph update leave
`matrix_world` stale, which would make that parent-matrix derivation wrong. All measuring —
assembly centre, radii, camera framing — happens while the scene is still at the assembled pose and
in sync, before any keyframes are written.

**Rotation continuity.** When writing euler rotations the current euler is passed to
`to_euler()` so the result stays continuous instead of snapping to an equivalent-but-different
representation. Camera pose interpolation uses quaternions for the same reason.

**Slotted actions.** Blender 4.4 moved keyframes into action slots and channelbags. The F-curve
helpers try the legacy `Action.fcurves` accessor first and fall back to walking the slotted
structure, so the add-on works across the 3.x–5.x range.

---

## Rendering

Once the animation exists it is ordinary Blender animation. Set up `Output Properties` and render
with `Ctrl+F12`. If `Make Scene Camera` is on, the generated camera is already the active scene
camera.

For a technical look, try `Sine` interpolation, `Radial Technical` spacing and an orthographic
camera. For an advert, try `Back` easing, a small rotation, and the `Product Showcase` preset.

---

## Testing

```bash
blender -b --factory-startup --python tests/test_addon.py
```

The suite builds a synthetic PCB product and drives the whole workflow: presets, saving state,
explode, assemble, all four direction modes crossed with all three spacing modes, parented and
rotated hierarchies, staggered sequencing, per-part overrides, exclusion, clearing animation, and
all three camera modes. Current result: **95 of 95 checks pass** on Blender 5.1.2.

The camera-framing tests re-derive the expected distance from the optics formula independently of
the add-on, and check that it scales correctly with both subject size and focal length.

The viewport capture operators need a real 3D viewport, so they are not covered headlessly; they
were verified separately in a GUI session, where captured framings reproduce to about `1e-7` and all
nine panels draw without error in every mode combination.

---

## Project layout

```text
exploded_assembly_studio/
├── __init__.py            bl_info and module registration
├── properties.py          scene settings and per-object data
├── core.py                state save/restore, explosion vectors, layering, ordering, keyframes
├── camera.py              camera rig, orbit, subject framing, viewport pose capture
├── operators.py           operators (Explode, Assemble, presets, camera, …)
├── ui.py                  sidebar panels
└── blender_manifest.toml  extension metadata for Blender 4.2+
build.py                   builds the installable zip
examples/demo_scene.py     mock PCB product to try the add-on on
tests/test_addon.py        headless test suite
```

`Exploded_Assembly_Studio_Specification.md` is the original design specification the add-on was
built from. It is written in Persian and kept for reference.

---

## Roadmap

Implemented in 1.x: everything in version 1.0 of the specification (source selection, assembly
state, explode/assemble, distance, all direction modes, frame range, interpolation, optional
rotation, clearing animation, undo safety), plus items pulled forward from later milestones — auto
and manual sequencing, per-part distance, staggered animation, hierarchy handling, and the
exploded-view camera with auto framing and viewport capture.

Not implemented, deliberately left for later per the specification: a constraint system
(mate/align/insert), multi-stage assembly timelines, automatic detection of part relationships from
geometry, and a technical-drawing mode.

---

## License

GPL-2.0-or-later, matching Blender's own licensing requirements for add-ons. See [LICENSE](LICENSE).
