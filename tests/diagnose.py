"""Print everything needed to explain why an enclosure is not animating.

Paste into Blender's Scripting workspace with your own file open and press Run.
It only reads: nothing in the scene is changed. Copy the whole output.
"""

import importlib

import bpy

# Installed as an extension the package lives under bl_ext, as a legacy add-on
# it is top level; find whichever one is actually loaded.
core = None
for key in list(bpy.context.preferences.addons.keys()):
    if "exploded_assembly_studio" in key:
        core = importlib.import_module(f"{key}.core")
        break
if core is None:
    core = importlib.import_module("exploded_assembly_studio.core")

props = bpy.context.scene.eas
source = props.collection
shell = props.enclosure_collection


def name_of(collection):
    return f"'{collection.name}'" if collection is not None else "NOT SET"


def contains(parent, target):
    """True when ``target`` is ``parent`` or nested anywhere below it."""
    if parent is None or target is None:
        return False
    if parent == target:
        return True
    return any(contains(child, target) for child in parent.children)


print("\n" + "=" * 68)
print("EXPLODED ASSEMBLY STUDIO - DIAGNOSTICS")
print("=" * 68)

version = [key for key in bpy.context.preferences.addons.keys() if "exploded" in key]
print(f"blender      : {bpy.app.version_string}")
print(f"add-on       : {version}")
print(f"file         : {bpy.data.filepath or '(unsaved)'}")

print("\n-- source ----------------------------------------------------------")
print(f"mode              : {props.source}")
print(f"source collection : {name_of(source)}")
if source is not None:
    print(f"                    {len(source.all_objects)} object(s) including sub-collections")
    print(f"                    children: {[c.name for c in source.children]}")
print(f"selected objects  : {len(bpy.context.selected_objects)}")
print(f"visible_only      : {props.visible_only}")
print(f"skip_child_parts  : {props.skip_child_parts}")

collected = core.collect_objects(bpy.context)
print(f"in range          : {len(collected)} object(s)")
if not collected:
    print(f"  why            : {core.source_report(bpy.context)}")

print("\n-- move together ---------------------------------------------------")
print(f"group_mode : {props.group_mode}   separator: {props.group_separator!r}")
if props.group_mode != 'NONE':
    sizes = {}
    for obj in collected:
        key = core.group_key(props, obj)
        sizes.setdefault(key, []).append(obj.name)
    multi = {key: names for key, names in sizes.items() if len(names) > 1}
    print(f"             {len(sizes)} part(s) from {len(collected)} object(s), "
          f"{len(multi)} built from more than one piece")
    for key, names in list(multi.items())[:5]:
        print(f"             {key[1]}: {names[:6]}")
    if not multi:
        print("             nothing grouped - the rule matches no two objects")

print("\n-- enclosure -------------------------------------------------------")
print(f"use_phases (Enclosure Closes Last) : {props.use_phases}")
print(f"enclosure collection               : {name_of(shell)}")
if shell is not None:
    usable = [o for o in shell.all_objects if o.type not in core.SKIPPED_TYPES]
    reachable = {o.name for o in collected}
    inside = [o for o in usable if o.name in reachable]
    print(f"                                     {len(shell.all_objects)} object(s), "
          f"{len(usable)} usable, {len(inside)} in range")
    print(f"nested inside the source           : {contains(source, shell)}")

tagged = [o for o in bpy.context.view_layer.objects
          if o.eas.role == 'ENCLOSURE' and not o.eas.is_rig]
print(f"marked Enclosure by hand           : {len(tagged)}")
if tagged:
    print(f"                                     {[o.name for o in tagged][:8]}")

panels = [o for o in collected if core.is_enclosure_member(props, o)]
print(f"panels the add-on will treat as shell : {len(panels)}")
if panels:
    print(f"  sides : {[(o.name, o.eas.side) for o in panels][:10]}")

hidden, outside, parented = core.missing_from_source(bpy.context, shell)
print(f"unreachable - hidden/excluded : {len(hidden)} {hidden[:5]}")
print(f"unreachable - outside Source  : {len(outside)} {outside[:5]}")
print(f"unreachable - follows a parent: {len(parented)} {parented[:5]}")
if not panels:
    print(f"  verdict : {core.enclosure_report(bpy.context)}")

print("\n-- timing ----------------------------------------------------------")
print(f"shot          : {props.frame_start} - {props.frame_end}")
print(f"component     : custom={props.component_custom_range} "
      f"{props.component_frame_start} - {props.component_frame_end}")
print(f"enclosure     : custom={props.enclosure_custom_range} "
      f"{props.enclosure_frame_start} - {props.enclosure_frame_end}")
print(f"parts window  : {core.parts_frame_range(props)}")
print(f"derived shell : {core.derived_enclosure_window(props)}")
print(f"parts_share   : {props.parts_share}   phase_gap: {props.phase_gap_frames}")
print(f"offscreen     : {props.enclosure_offscreen}  avoid_camera: "
      f"{props.enclosure_avoid_camera}  margin: {props.enclosure_camera_margin}")
print(f"shell distance: {props.enclosure_distance_factor}")

print("\n-- keyframes actually written --------------------------------------")


def key_range(obj):
    frames = [
        point.co[0]
        for curve in core.iter_fcurves(obj)
        for point in curve.keyframe_points
    ]
    return (min(frames), max(frames), len(frames)) if frames else None


keyed = [(o.name, key_range(o)) for o in collected]
with_keys = [item for item in keyed if item[1]]
print(f"{len(with_keys)} of {len(collected)} collected object(s) have transform keys")
panel_names = {o.name for o in panels}
panel_keys = [item for item in with_keys if item[0] in panel_names]
print(f"of which {len(panel_keys)} are enclosure panels")
for name, span in panel_keys[:10]:
    print(f"  {name}: frames {span[0]:.0f}-{span[1]:.0f}, {span[2]} keys")
if panels and not panel_keys:
    print("  NO PANEL HAS KEYS - the enclosure was not animated")

print(f"last build mode : {props.last_build_mode}")
print("=" * 68 + "\n")
