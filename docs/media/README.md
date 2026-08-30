# Media for the README

Drop screenshots and animations here, then uncomment the matching lines in the
[Gallery](../../README.md#gallery) section of the main README.

## What goes where

| File | What it shows |
|---|---|
| `demo.gif` | The hero animation, autoplaying at the top of the README |
| `panel-source.png` | The Source and Presets panels |
| `panel-enclosure.png` | The Enclosure panel with a collection picked and sides detected |
| `panel-filtering.png` | Filtering, with `Move Together` on and the group count visible |
| `panel-camera.png` | The Camera panel with viewpoints in the list |
| `exploded.png` | A still of the exploded view |
| `assembled.png` | The same product assembled, for a before/after pair |

Names are a suggestion, not a rule — anything you reference from the README works.

## Images

Straight into the repo, referenced with a relative path:

```markdown
![The Enclosure panel](docs/media/panel-enclosure.png)
```

Keep them under about 500 KB each. PNG for panels (sharp text, flat colour), JPEG
for rendered stills. A sidebar screenshot is usually 300-400 px wide — crop to the
panel itself rather than the whole Blender window, so the text stays readable
without clicking.

## Video: the part that catches people out

**A committed `.mp4` does not play in a README.** A relative link to one in the
repo renders as a download link, and a `<video>` tag is stripped. Two things do
work:

### GIF — always plays, no upload dance

Commit it like an image. It autoplays, loops, and works on every mirror. This is
the right choice for a short hero clip.

```markdown
![Assemble animation](docs/media/demo.gif)
```

Keep it to 5-10 seconds and under ~8 MB, or GitHub gets slow to load.

### MP4 — better quality, needs GitHub to host it

GitHub only plays video it hosts itself. Upload it by dragging the file into the
comment box of any issue, pull request, or release on the repo — **do not commit
it**. GitHub replaces it with a URL like:

```
https://github.com/user-attachments/assets/0a1b2c3d-...
```

Put that URL **on a line of its own** in the README and it renders as a player
with controls. You can close the issue afterwards; the asset stays.

For a long walkthrough, attach the full quality file to a
[Release](https://github.com/ehsun-sh/blender-exploded-assembly-studio/releases)
as well, so people can download it rather than stream it.

## Making the files

Render the animation from Blender as a PNG sequence or an MP4, then:

```bash
ffmpeg -i render.mp4 -vf "fps=15,scale=800:-1:flags=lanczos,palettegen=stats_mode=diff" -y palette.png
```

```bash
ffmpeg -i render.mp4 -i palette.png -lavfi "fps=15,scale=800:-1:flags=lanczos,paletteuse=dither=bayer:bayer_scale=3" -y docs/media/demo.gif
```

Two passes because a shared palette generated from the whole clip is what keeps a
GIF from banding. `fps=15` and `scale=800` are the knobs to turn if the file comes
out too big.

For the MP4 that GitHub will host, re-encode for size rather than uploading the
raw render:

```bash
ffmpeg -i render.mp4 -c:v libx264 -pix_fmt yuv420p -crf 24 -vf "scale=1280:-2" -movflags +faststart -an -y demo.mp4
```

`-pix_fmt yuv420p` matters: Blender can write a pixel format Safari and some
browsers will not decode, and the video then silently fails to play for a share of
your readers.
