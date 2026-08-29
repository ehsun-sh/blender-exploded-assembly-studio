# Changelog

All notable changes to Exploded Assembly Studio are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [1.10.3]

### Fixed

- **Restoring a snapshot quietly forgot the enclosure collection.** ID pointers were restored by
  looking the saved name up in a hand written map of settings, and `Enclosure Collection` had never
  been added to it, so the name was looked for among objects, found nothing, and the setting came
  back empty. The enclosure then stopped being an enclosure, and `Detect Sides` reported that nothing
  was tagged — with the collection still showing in the panel, because the restore ran before the
  panel redrew. Pointers now resolve through the property's own type, so a setting added later cannot
  be looked up in the wrong place.
- **A panel parented to a part was reported as "hidden or excluded".** `Skip Parented Children` drops
  it on purpose — it already follows the part it hangs off — but the message sent you into the
  Outliner looking for something that was never hidden. That is now its own category, in `Detect
  Sides` and in the Enclosure panel, naming the switch to turn off.

### Changed

- The "nothing is an enclosure panel yet" warning now carries its own diagnosis: the enclosure
  collection by name (or that none is set), how many of its objects the add-on can currently reach,
  and how many objects are marked Enclosure by hand.

## [1.10.2]

### Fixed

- **A hidden source collection now names the exact switch hiding it.** "Hidden or excluded" covers
  three different controls in three different places in the Outliner — the exclude checkbox, the eye
  icon and the monitor icon — and a parent collection can be the one responsible, so the row to click
  may not be the one you are looking at. The message now names the collection and the control, and
  distinguishes those from objects hidden one by one.

### Added

- **Use Hidden Objects** button, offered in the Source box whenever nothing could be collected. It
  turns off `Visible Only` in one click. Hiding a heavy assembly for viewport performance is
  reasonable and should not have to be undone before animating it: only transforms and keyframes are
  written, and neither needs an object to be visible.

### Notes

Measured on a 2315 object assembly, the size of a real ECAD import: Set Assembly Position 0.01 s,
first build 0.31 s, rebuild 0.37 s, clear 0.14 s.

## [1.10.1]

### Fixed

- **"The collection has no usable objects" said nothing useful.** The same line came out of four
  unrelated situations — an empty source collection, one hidden in the outliner, one excluded from
  the view layer, and one never chosen — and it never named the collection it meant, so a perfectly
  good enclosure setup looked like the thing that had broken. Every case now names the collection
  and the fix, including which setting overrides it.
- `Detect Sides` now reports when the enclosure panels themselves are the unreachable ones, and
  distinguishes panels sitting **outside the Source set** from panels that are **hidden or excluded**
  — those are fixed in different places. The Enclosure panel makes the same distinction.
- Nothing tagged as an enclosure yet is now a warning naming both ways to fix it, rather than an
  error.

## [1.10.0]

### Changed

- **All three frame ranges now speak the same language.** The Animation panel has one group each for
  `Shot`, `Component` and `Enclosure`, and every one of them is a `Start Frame` and an `End Frame`.
  Previously the shot used absolute frames while the components used `Pre Action` / `Post Action`
  offsets and the enclosure lived in a different panel entirely — three ways of saying when something
  happens.
- `Pre Action` and `Post Action` are replaced by **Component → Custom Range** with explicit start and
  end frames. Switching it on seeds them from the shot, so it starts as a no-op.
- The enclosure's timing moved from the Enclosure panel to the Animation panel, next to the other two.
  The Enclosure panel now covers only *which* objects are panels and *how* they move.
- One box in the Animation panel lists every window at once — shot, components, enclosure, camera —
  so nothing has to be inferred.

### Added

- **Enclosure Collection.** Point at a collection and every object in it counts as an enclosure
  panel, without tagging them one by one. Hand tagged objects still count alongside it, and `Detect
  Sides` works off both. The panel warns when collection members sit outside the Source set, since
  those would never be animated.

### Notes

Scenes that used `Pre Action` / `Post Action` will open with the components spanning the whole shot.
Set them again under Component → Custom Range; the frames are the same numbers the old offsets
produced.

## [1.9.0]

### Added

- **Custom Frame Range for the enclosure.** The shell can be given its own start and end frame
  instead of deriving them from `Parts Share` and `Phase Delay`. The parts keep the window that
  `Pre Action` and `Post Action` give them, so the two are timed completely independently and the
  shell can run past the end of the parts window.
- Switching it on seeds the fields from whatever the automatic split was already producing, so an
  explicit range continues what was happening rather than jumping to arbitrary numbers.
- Both windows are shown together in the panel, with a warning when the shell would start before the
  parts finish. That is allowed — an explicit range is the user's call — but it means the case closes
  over a board that is still filling up.
- Inverted start and end frames are ordered rather than producing an inverted window.

## [1.8.0]

### Added

- **Pre Action and Post Action.** Frames at each end of the shot where the parts stay put while the
  camera keeps moving, so a shot can open on a camera move before anything assembles and carry on
  around the finished product afterwards. No separate camera list is needed for those stretches: the
  camera path already spans the whole shot, so a viewpoint's `Time` places it wherever you want.
- A timing readout in both panels showing the shot range, the frames the camera moves over, and the
  frames the parts move over, so the two sets of delays are readable at a glance.

### Changed

- **The camera hold is now labelled `Start Delay` and `End Delay`, and sits at the top of the Camera
  panel.** It was called "Hold Start"/"Hold End" and sat underneath the per-mode settings, which in
  From Viewport mode meant scrolling past a viewpoint list to reach it. A timing control nobody can
  find is a timing control that does not exist.

### Removed

- Dead `part_timing` helper, superseded by the phase-aware timing added in 1.3.0.

## [1.7.0]

### Added

- **Start Off Camera for parts.** Previously only enclosure panels could be parked out of shot, so an
  assemble animation opened with the parts already visible around the board. Each part is now pushed
  along its own explode direction until it is fully outside the camera frame, using the same frustum
  solve. It only changes the distance, never the direction, and acts as a minimum so layered spacing
  above the threshold survives. Parts travelling straight away from the camera can never leave frame
  and are reported rather than moved pointlessly far.
- **Drop In From Above** preset: parts wait above the shot, out of frame, and drop straight down onto
  the board one after another, with the camera held at the start. Built for the Assemble direction.
- With parts starting off camera, the framing now measures the assembled product rather than where
  the parts wait, so the camera no longer pulls back to include them.

### Changed

- The **Restore** button is now called **Preview Assembled**. It always was the assembled preview,
  but the old name read like an undo. In an assemble animation the exploded state is the first frame
  and the assembled state the last, so both previews are useful whichever direction you work in.
- **Preview Exploded** now applies the same off-camera placement the animation uses, so what it shows
  is exactly the first frame of an assemble.

## [1.6.0]

### Added

- **Snapshots.** A restore point holding every setting, the camera path, per-object data and where
  the parts are sitting. Take one before experimenting and come back to it whenever a round of
  changes goes nowhere. Several can be kept side by side under their own names, and they live in the
  .blend so they survive saving and reloading.
- Restoring clears the generated keyframes too, so parts stay where the snapshot put them. Because
  the settings come back as well, including which animation was built last, pressing Rebuild
  afterwards recreates exactly the animation that existed at the time.
- Snapshots are stored as JSON, so one taken by an older version stays readable when settings are
  added or renamed later: anything unknown is skipped rather than failing. Objects renamed or
  deleted since the snapshot are reported and skipped rather than blocking the restore.

### Notes

A snapshot is stored inside the .blend, so it is a complement to saving the file, not a replacement
for it. If Blender closes unexpectedly before a save, the snapshot goes with the work.

## [1.5.0]

### Added

- **Rebuild button.** Settings only take effect on the next build, so this repeats whichever
  animation was built last — the button reads `Rebuild Assemble` or `Rebuild Explode` — without the
  risk of flipping the direction while tweaking. It is safe at any frame and never stacks up
  duplicate keys, because parts are always measured from the saved assembly position rather than
  from where they currently sit. Clearing the animation forgets what was built.
- A "Checking it works" walkthrough in the README for validating a setup before rendering.

## [1.4.0]

### Added

- **Start Off Camera.** Enclosure panels are now parked far enough away to be completely outside the
  camera frame while the parts are landing, so a shell waiting to close never blocks the view of the
  board. The distance is solved from the camera frustum rather than guessed: the frustum planes all
  pass through the camera, so the test for one plane is linear in the travel distance and solves
  directly. `Shell Distance` becomes a minimum when this is on.
- **Never Enter Past Camera.** A panel whose own side faces the camera is given a different entry
  direction, so it never sweeps across the lens on its way in. A front panel in a front view comes
  down from above instead. The substitute is the side closest to the natural one that is still clear
  of the camera, so the change stays as small as the geometry allows.
- The camera framing now ignores panels that are parked off camera, so sending a shell out of frame
  no longer drags the camera back to include it.
- `Off Camera Margin` for extra clearance beyond the edge of frame.

### Changed

- **`Phase Gap` is now `Phase Delay`, set in frames** rather than as a fraction of the range, and the
  panel shows it in seconds at the scene frame rate. The enclosure phase could already never begin
  before the last part landed; the delay on top of that is now a number you set directly.
- The camera hold now also reads out in seconds.

### Notes

Two directions can never hide a panel, and the add-on now handles both: travelling straight away
from the camera only makes a panel smaller, so it never leaves frame, and travelling straight at the
camera only clears the frame by flying past the lens. Both are rejected in favour of a sideways
entry.

## [1.3.0]

### Added

- **Camera hold.** `Hold Start` and `Hold End` keep the camera still for a number of frames at each
  end of the shot, so the beginning of the assembly is not competing with a camera move. The parts
  keep the full frame range; only the camera waits.
- **Multiple camera viewpoints.** The From Viewport mode now takes any number of viewpoints instead
  of just a start and an end, managed in a list: add from the current view, update, reorder, remove,
  look through, or space evenly. Each viewpoint carries its own time, focal length and roll.
- **Per segment motion.** The move between two viewpoints can be `Linear` or `Arc`. An arc curves
  around the subject rather than cutting the chord, which a plain keyframe pair cannot do — it is
  baked as sampled keys, with the segment's easing folded into where each sample lands in time so
  the timing curve survives. Interpolation and easing are set per segment.
- **Roll** per viewpoint, tilting the camera around its own view axis.
- **Enclosure panels as a separate phase.** Objects can be marked as `Part` or `Enclosure`. Enclosure
  panels open along their own side — top, bottom, front, back, left, right — instead of following the
  global explode direction, and they move in their own phase: on Assemble the inner parts land first
  and the shell closes over them, on Explode the shell opens before the parts come out.
  `Detect Sides` works each panel's side out from where it sits, and any panel can be overridden by
  hand to enter from a different side. `Parts Share`, `Phase Gap` and `Shell Distance` control the
  split.

### Changed

- A scene saved with the old two-pose camera is migrated into the viewpoint list on first use, so
  existing files keep working.

## [1.2.0]

### Fixed

- **The camera played backwards when building an Assemble animation.** The captured start framing
  ended up on the last frame and the end framing on the first. Assemble is the natural choice for a
  product that builds itself — components landing on the board, shells closing over it — so this hit
  the main workflow. The start framing is now the first frame of whatever you build, in every camera
  mode. The same applied to Orbit mode, where Start Angle was silently swapped with the end of the
  orbit.

### Added

- **Mirror On Assemble** camera option, off by default. Turning it on restores the previous
  behaviour, which is useful if you render an Explode pass and an Assemble pass and stitch them
  together, since the camera then continues where the first pass ended.

## [1.1.0]

### Added

- **Frame Object camera mode.** Pick a reference object — normally the PCB — and the camera derives
  its distance from that object's bounding sphere, the focal length, the sensor size and the render
  aspect ratio. The computed distance and subject size are shown live in the panel, in the scene's
  own units.
- **From Viewport camera mode.** Capture the first and last camera framing straight from the 3D
  viewport, either from an ordinary user view or from inside the camera preview with
  *Lock Camera to View* enabled. Focal length is captured with each pose and can be animated across
  the shot. Poses are keyed on quaternion channels so the camera turns the short way between
  orientations.
- *Look through pose* buttons that send the viewport back to a captured framing for checking.
- *Use Active Object* button and a *Clear Captured Poses* action for the new camera modes.
- The **PCB Product** preset now also sets the camera to frame the active object, so the board
  defines both the explosion split plane and the framing.
- `examples/demo_scene.py`, a mock PCB product for trying the add-on without a model of your own.

### Fixed

- Camera framing measured the subject in the wrong place when built as part of an explode. Keyframes
  are written straight to object transforms, which leaves `matrix_world` stale until the depsgraph
  updates, and the parent-matrix derivation then resolved incorrectly. All framing is now measured
  before any keyframes are written, while the scene is still at the assembled pose and in sync.

### Changed

- Camera framing is resolved once by the calling operator rather than inside the rig builder, so
  there is a single, well-defined point where the scene has to be in a consistent state.

## [1.0.0]

Initial release, covering version 1.0 of the design specification plus several items pulled forward
from later milestones.

### Added

- Source selection from the current selection or from a collection.
- Assembly state saved per object as a local matrix, restored exactly on assemble.
- Explode and assemble animation generation with configurable frame range.
- Four explosion directions: From Center, Axis +/- (Split), World Axis, Local Axis.
- Three spacing modes: Uniform, Proportional, Layered — with layer clustering so parts at the same
  depth travel together instead of fanning into a staircase.
- Assembly centre from bounding box, median point, 3D cursor or the active object.
- Optional rotation during the explosion, around a world or local axis.
- Staggered sequencing with configurable order, overlap and mirrored assemble order.
- Per-part distance multiplier, manual order and exclusion.
- Orbiting camera rig with auto framing and an optional dolly.
- Three presets: PCB Product, Radial Technical, Product Showcase.
- Clear Animation, which removes the generated channels and restores the assembled model.
- Parent handling: children of a moving parent ride along rather than moving twice.
- Headless test suite.

### Notes

- The add-on never modifies meshes, materials, modifiers or origins — only transforms and keyframes.
- All operators are undo-compatible.
- Works across Blender 3.x to 5.x, including the slotted actions introduced in 4.4.
