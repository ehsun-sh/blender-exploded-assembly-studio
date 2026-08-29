# Exploded Assembly Studio

A Blender add-on that turns an assembled model into an **exploded view** and builds the animation
both ways — explode and assemble — with an optional camera move. It is aimed at product
visualisation for electronics and mechanical hardware: PCBs and enclosures, housings, gearboxes,
network gear, anything that comes apart into layers.

**Version 1.10.2** · tested on **Blender 5.1.2** · minimum **Blender 4.2** (extension install) or
**Blender 3.0** (legacy add-on install)

```text
Assembled model  →  Explode animation  →  Exploded view  →  Assemble animation  →  Assembled model
```

---

## Table of contents

- [What it does](#what-it-does)
- [Install](#install)
- [Quick start: a PCB product](#quick-start-a-pcb-product)
- [Checking it works](#checking-it-works)
- [Try it without a model](#try-it-without-a-model)
- [Panel reference](#panel-reference)
  - [Source](#source)
  - [Presets](#presets)
  - [Explosion](#explosion)
  - [Rotation](#rotation)
  - [Sequence](#sequence)
  - [Enclosure](#enclosure)
  - [Animation](#animation)
  - [Camera](#camera)
  - [Snapshots](#snapshots)
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

That produces `dist/exploded_assembly_studio-1.10.2.zip`.

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

### Changing a setting afterwards

Every setting is read fresh each time an animation is built, and the parts are always measured from
the saved assembly position rather than from wherever they happen to be sitting. So the loop is:

```text
change a setting  →  press Rebuild  →  watch  →  repeat
```

**Rebuild** repeats whichever of the two you built last — the button says so, `Rebuild Assemble` or
`Rebuild Explode` — so you cannot accidentally flip the direction of the animation while tweaking.
It is safe to press at any frame, as often as you like, and it never stacks up duplicate keyframes.
There is no need to undo, clear, or return to frame 1 first.

---

## Checking it works

A quick pass to confirm a setup is sound before committing to a render:

1. **Save the file first.** Everything below is undoable, but a saved file is a better safety net.
2. **Press Set Assembly Position** with the parts where they belong. The Source line should report
   the number of parts you expect — if it says fewer, something is hidden or outside the collection.
3. **Press Preview Exploded.** This moves the parts with no keyframes, so you can see the spread
   instantly. Too much or too little? Change `Distance` and press it again. Then **Restore**.
4. **Build the animation** and scrub the timeline by hand rather than playing it. Playback hides
   ordering problems that scrubbing makes obvious.
5. **Check frame 1 and the last frame.** For an assemble, the last frame must look exactly like the
   product you started with. If it does not, the assembly position was saved from the wrong state —
   restore, fix, and save it again.
6. **Check the camera through the lens**, not from a user view. Press <kbd>Numpad 0</kbd> and scrub
   again: a move that looks fine in the viewport can crop parts in the render frame.
7. **Render a low-quality preview** before the real one — small resolution, a low sample count, every
   nth frame. Most framing and timing mistakes show up in a 20-second preview.

If something looks wrong, the fastest diagnosis is **Clear Animation**, which strips the generated
keyframes and puts every part back to its saved assembly position, leaving you where you started.

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
| Visible Only | Skip objects hidden in the current view layer. **Turn this off to work on a hidden assembly** — only transforms and keyframes are written, and neither needs an object to be visible |

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
| **Drop In From Above** | Parts wait above the shot, out of frame, and drop straight down onto the board one after another. Built for Assemble. |

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
| Start Off Camera | Push every part along its own direction until it starts outside the camera frame. `Distance` becomes a minimum. |
| Center | Reference point: Bounding Box, Median Point, 3D Cursor, or **Active Object**. |
| Layer Tolerance | How close in depth two parts must be to count as the same layer. |
| Use Geometry Center | Measure parts from their bounding-box centre instead of their origin. Turn this off for CAD models whose origins carry meaning. |

**If your parts end up in a ring around the board**, the direction is `From Center`. On a flat board
a radial spread has nowhere to go but sideways, so it lays the parts out in a circle. For parts that
come down from above, use `World Axis` on `Z` — or just apply the **Drop In From Above** preset.

**Start Off Camera** solves the other half of that: parts sitting a short distance above the board
are still in shot at the first frame. With it on, each part is pushed along its own direction until
it is fully outside the camera frame, using the same frustum solve the enclosure uses, so an
assemble animation opens on an empty shot and the parts fly in. It only changes the distance, never
the direction, and it acts as a minimum — a part already travelling further stays where it was.
A part travelling straight away from the camera can never leave frame, and is reported rather than
moved pointlessly far.

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

### Enclosure

For a product in a shell, the parts and the case want different treatment. Tag them and the add-on
animates them as two phases:

```text
ASSEMBLE:   components land on the board   →   pause   →   shell closes in from every side
EXPLODE:    shell opens outwards           →   pause   →   parts come off the board
```

1. Point **Collection** at the collection holding the shell panels — or select them and press
   **Mark Enclosure**. (The opposite button puts them back to parts.) Either one switches
   `Enclosure Closes Last` on for you.
2. **Detect Sides** works out which way each panel opens from where it sits — a lid above the product
   reads as Top, a panel out to the left reads as Left. Only the sides your product actually has get
   used, so a case with just a top and a bottom gets exactly those two.
3. Build the animation.

The enclosure collection does **not** have to live inside the Source collection. Choosing it here is
enough: its objects join the assembly wherever they sit in the outliner. Objects tagged by hand with
`Mark Enclosure` still have to be reachable from Source, and the button says so if they are not.

Enclosure panels ignore the global explode direction and travel along their own side instead, which
is what makes a six-sided case open outwards like a box rather than fanning along one axis.

| Option | What it does |
|---|---|
| Collection | Every object in this collection counts as an enclosure panel, no tagging needed |
| Mark Enclosure / Mark Part | Tag objects by hand, alongside or instead of the collection |
| Start Off Camera | Park each panel completely outside the camera frame until its own phase begins |
| Never Enter Past Camera | Stop a panel entering from the side the camera is on |
| Off Camera Margin | Extra clearance beyond the edge of frame when parking panels |
| Shell Distance | Extra travel for panels. A minimum when `Start Off Camera` is on |

In automatic mode the shell **never** starts before every part has landed — that is structural, not
a matter of tuning `Parts Share`. `Phase Delay` is the pause on top of it.

**Custom Frame Range** detaches the two completely. The parts keep the window that `Pre Action` and
`Post Action` give them, and the shell gets the exact start and end frame you type:

```text
shot     1 ─────────────────────────────────────────── 200
parts         21 ──────────────────── 170
shell                                      150 ─── 195
```

Switching it on seeds the fields from whatever the automatic split was already doing, so you start
from what you had. The panel shows both windows together, and warns if the shell would begin before
the parts finish — that is allowed, since it is your call, but it means the case closes over a board
that is still filling up.

#### Keeping the shell out of the shot

Two options decide where a panel waits, and they matter more than they sound. A shell panel parked a
short distance away still sits in frame, covering the board while the parts are landing; and a panel
that enters from the camera's own side sweeps across the lens on its way in.

**Start Off Camera** parks each panel far enough out to be completely clear of frame. The distance is
solved from the camera frustum rather than guessed — the frustum planes all pass through the camera,
so the condition for one plane is linear in the travel distance and solves directly, for every
camera position in the shot.

**Never Enter Past Camera** gives a panel a different entry side when its own faces the lens, picking
the side closest to its natural one that is still clear.

Two directions can never hide a panel, and both are handled:

```text
straight away from the camera  →  only gets smaller, never leaves frame
straight at the camera         →  only clears frame by flying past the lens
```

So a front panel in a front view comes down from above, and so does a back panel — neither can hide
along the view axis. The camera framing ignores parked panels, so sending a shell out of frame does
not drag the camera back to include it.

Any panel can be overridden in **Active Part → Side**. That covers the case where the automatic
guess is right but the shot is not: a front panel can be told to come down from above instead of
sliding in from the front.

### Animation

Start and end frame, interpolation (Bezier, Linear, Sine, Quadratic, Cubic, Exponential, Back,
Elastic) and easing direction. `Back` and `Elastic` give the slight overshoot that reads as
"product advert"; `Sine` with ease-in-out is the safe technical choice.

**EXPLODE builds assembled → apart. ASSEMBLE builds apart → assembled.** Pick the one that matches
the story you are telling: for a product that builds itself, components dropping onto the board and
the shells closing over it, that is **ASSEMBLE**.

`Replace Existing` clears the add-on's transform channels before writing new ones, so repeated
clicks never stack up duplicate keys. `Auto Save Assembly State` records the assembled pose for any
part that does not have one yet, so a first-time explode works even if you forget step 5.

### Camera

#### Delays, and who moves when

The frame range is the **whole shot**. Two pairs of settings carve it up, and they are independent:

| Setting | Where | What waits |
|---|---|---|
| `Start Delay` / `End Delay` | Camera panel, at the top | The **camera** holds still; the parts carry on |
| `Pre Action` / `Post Action` | Animation panel | The **parts** hold still; the camera carries on |

```text
shot        1 ─────────────────────────────────────── 120
parts             31 ──────────────────── 100
camera      1 ─────────────────────────────────────── 120
            └ pre action ┘             └ post action ┘
```

**Pre Action** and **Post Action** are how a shot opens on a camera move before anything assembles,
and carries on around the finished product afterwards. You do not need a separate camera list for
those stretches: the camera path already spans the whole shot, so add viewpoints and set their
`Time` to place them wherever you want, including inside the pre and post windows.

`Start Delay` and `End Delay` do the opposite — they park the camera. This matters more than it sounds: a camera that starts moving on frame 1
competes with the parts for attention, and the beginning of the assembly gets lost. Holding for the
first 10–20 frames lets the viewer watch the parts land, then the camera takes over.

The parts always keep the full frame range — only the camera waits. The panel shows the frames the
camera actually moves over.

#### The three modes

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

Instead of numbers, capture the camera path straight from the viewport, one viewpoint at a time:

1. Frame the opening shot in the viewport → **Add From View**
2. Frame the next one → **Add From View** again. Repeat for as many as you want; two behaves like a
   simple A-to-B move.
3. Build the animation — the camera travels through the viewpoints in time order.

The list shows each viewpoint with the frame it lands on, its focal length and the motion leaving it.
The buttons beside it add, remove and reorder; the ↻ button re-captures the active viewpoint from the
current view, and 👁 sends the viewport to it.

Each viewpoint carries its own settings:

| Setting | What it does |
|---|---|
| Time | Where it sits in the camera move, `0` first frame, `1` last. **Space Evenly** resets them |
| Focal Length | Captured with the view; blended along the path when `Animate Focal Length` is on |
| Roll | Tilts the camera around its own view axis at this viewpoint |
| Motion | How the camera travels to the **next** viewpoint: `Linear` or `Arc` |
| Interpolation / Easing | Timing of the segment leaving this viewpoint |

**Arc** curves the camera around the subject instead of cutting straight across. A plain pair of
keyframes always gives a straight line, so an arc is baked as sampled keys along the circle — the
segment's easing is folded into where each sample lands in time, so the timing curve survives the
baking. `Arc Quality` sets how many frames apart those samples are.

Both of these work:

- **From an ordinary user view.** Just orbit the viewport. No camera has to exist yet.
- **From inside the camera preview.** Click `Camera View` (or Numpad 0), turn on `Lock To View`, and
  the viewport moves the camera itself, so what you capture is exactly the render framing. Both
  buttons are in the panel.

Notes:

- **Focal length is captured too.** Grab the first viewpoint at 35 mm and the last at 85 mm and, with
  `Animate Focal Length` on, the lens blends across the shot.
- Rotation is keyed on the quaternion channel so the camera turns the short way between the two
  orientations instead of unwinding through euler gimbal.
- In this mode the camera has no parent and no aim constraint, so the captured framing is exactly
  what renders. Switching back to Orbit rebuilds the rig.
- The start framing is the first frame of whatever you build, Explode or Assemble. If you want to
  render both passes and stitch them together, turn on **Mirror On Assemble** and the assemble pass
  plays the camera backwards so it continues where the explode pass ended.

### Snapshots

A restore point for **every setting** plus where the parts are sitting. Take one before you start
experimenting, then come back to it whenever a round of changes goes nowhere.

| Button | What it does |
|---|---|
| Take Snapshot | Store the current settings, camera path, per-part data and transforms |
| Restore | Put all of that back |
| ↻ | Overwrite the selected snapshot with the current state |

Restoring clears the generated keyframes as well, so the parts actually stay where the snapshot put
them. Since the settings come back too — including which animation was built last — pressing
**Rebuild** straight afterwards recreates exactly the animation that existed when you took it.

Snapshots are stored inside the .blend, so they survive saving and reloading, and several can be
kept side by side under whatever names you give them. Objects renamed or deleted since the snapshot
are reported and skipped rather than blocking the restore.

> A snapshot is **not** a substitute for saving the file. It lives inside the .blend, so if Blender
> closes unexpectedly before you save, the snapshot goes with the work. Use both.

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
all three camera modes, the enclosure phase and the multi viewpoint camera. Current result: **301 of 301 checks pass** on Blender 5.1.2.

The camera-framing tests re-derive the expected distance from the optics formula independently of
the add-on, and check that it scales correctly with both subject size and focal length.

The viewport capture operators need a real 3D viewport, so they are not covered headlessly; they
were verified separately in a GUI session, where captured framings reproduce to about `1e-7` and all
eleven panels draw without error in every mode combination.

### When something is not animating

Open your own file, paste `tests/diagnose.py` into the Scripting workspace and press Run. It changes
nothing and prints what the add-on can actually see: which collections are set, how many of their
objects are in range, what counts as an enclosure panel, the frame windows, and which objects ended
up with keyframes. That output usually names the problem outright.

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
