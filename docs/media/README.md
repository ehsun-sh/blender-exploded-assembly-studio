# Media for the README

Drop screenshots and animations here, then uncomment the matching lines in the
[Gallery](../../README.md#gallery) section of the main README.

## What goes where

| File | What it shows | In the README |
|---|---|---|
| `demo.mp4` | The assemble animation, 1000 px | Hero, via the attachment URL |
| `demo.gif` | The same clip, 480 px | Nowhere — held as a fallback |
| `sidebar.png` | The add-on's sidebar panel | Gallery |

`demo.gif` is deliberately not displayed. It is a quarter of the resolution at
twice the size, and stacking two copies of one eight second clip at the top of the
page helped nobody. It is kept because the video depends on GitHub hosting it, and
a GIF renders anywhere a Markdown file does — a mirror, a clone, an IDE preview.
To fall back to it, put this above the video line:

```markdown
![A bare board, its components landing, the enclosure closing over them](docs/media/demo.gif)
```

Suggestions for more, whenever you take them — the names are not a rule, anything
you reference from the README works:

| File | What it would show |
|---|---|
| `panel-enclosure.png` | The Enclosure panel with a collection picked and sides detected |
| `panel-filtering.png` | Filtering, with `Move Together` on and the group count visible |
| `panel-camera.png` | The Camera panel with viewpoints in the list |
| `exploded.png` / `assembled.png` | A before/after still pair |

## Why demo.gif is not the file you rendered

The GIF here is rebuilt from `demo.mkv` rather than exported directly, because a
GIF of a rendered 3D clip is nearly all background gradient, and that is the one
thing the format is worst at. Shrinking it by dropping resolution makes the
product soft while barely helping; the size is in the gradient, not the detail.

What actually works is capping the palette and dithering it, at full resolution:

```bash
ffmpeg -i demo.mkv -vf "fps=12,scale=480:-1:flags=lanczos,palettegen=max_colors=128:stats_mode=diff" -y palette.png
```

```bash
ffmpeg -i demo.mkv -i palette.png -lavfi "fps=12,scale=480:-1:flags=lanczos,paletteuse=dither=bayer:bayer_scale=3" -y demo.gif
```

`max_colors=128` is what keeps the file down; the dither is what stops 128 colours
banding across a smooth grey backdrop. Dropping the dither saves another 1.5 MB and
puts visible rings in the background — not worth it.

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

### MKV does not work at all

GitHub plays `.mp4`, `.mov` and `.webm`. Matroska is not on the list, and the
attachment uploader rejects the extension outright — so an `.mkv` can neither be
embedded nor uploaded, however good it looks locally.

It converts for free, though. A Blender-rendered MKV is normally already H.264 in
a Matroska wrapper, so changing the container copies the video stream untouched —
no re-encode, no quality loss, and it takes about a second:

```bash
ffmpeg -i demo.mkv -c copy -movflags +faststart -y demo.mp4
```

`-movflags +faststart` moves the index to the front of the file so playback can
begin before the whole thing has downloaded. If `-c copy` errors, the stream is
something other than H.264 and needs the real encode further down.

### MP4 — better quality, needs GitHub to host it

GitHub only plays video it hosts itself. Committing the file does not make it
playable, and neither does linking to it — a relative link reaches the blob page,
which refuses to preview anything this size. Upload it by dragging the file into
the comment box of an issue, pull request, or release. GitHub replaces it with a
URL like:

```
https://github.com/user-attachments/assets/0a1b2c3d-...
```

Put that URL **on a line of its own** in the README and it renders as a player
with controls. Do not wrap it in a link or an `<img>` tag — a bare line is what
GitHub looks for.

**Submit the comment.** Uploading is not enough: until some submitted content
references the asset, the URL returns 404 to everyone except you, so the README
looks fine while you are logged in and is broken for every visitor. That is what
[issue #1](https://github.com/ehsun-sh/blender-exploded-assembly-studio/issues/1)
is for — it holds the current demo alive. Closing it is fine; deleting it breaks
the player.

Check it the way a visitor sees it, not from a logged-in tab:

```bash
curl -sSL -o /dev/null -w "%{http_code} %{content_type}\n" -r 0-4095 "https://github.com/user-attachments/assets/..."
```

`206 video/mp4` means it is live. `404` means the referencing comment was never
submitted.

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
