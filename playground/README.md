# playground

Throwaway probes. **Nothing here is imported by the application**, nothing
here is tested, and anything in this folder may be deleted without notice
once it has answered the question it was written for.

A previous `playground/` held the recycling detection pipeline while it was
a standalone prototype. That one was deleted on purpose when the pipeline
moved into `app/plugins/recycling/` — the lesson being that a prototype
which grows a second home tends to keep it. These files are different in
kind: single-file probes that answer one question and then go.

## Files

| File | Question it exists to answer |
|---|---|
| `frame_extractor.html` | Can the browser pull usable stills out of a phone video, and does evenly-spaced sampling actually cover a room? |

## frame_extractor.html

Open it directly — no server, no build step:

```
start playground/frame_extractor.html
```

Pick a video, choose how many frames, press Extract. It reports the source
duration and resolution, the wall-clock time, and the **total payload of
the extracted frames versus the size of the video** — that ratio is the
argument for extracting in the browser instead of uploading the recording.

Two sampling strategies:

- **Evenly spaced** — the naive approach. N frames at equal intervals.
- **Prefer still moments** — decodes 3N candidates and keeps the N that
  differ least from the frame before them, as a rough proxy for "the
  camera had stopped moving". A frame captured mid-pan is both
  motion-blurred and given fewer bits by the encoder, so it is the worst
  kind of frame to hand a vision model.

If "prefer still moments" is visibly better on real footage, motion-aware
sampling is worth building properly. If it is not, evenly spaced is
sufficient and the video path gets much simpler.

**Expect failures on some files.** An iPhone records HEVC by default, and a
browser without a hardware HEVC decoder cannot open it at all — the page
says so rather than failing silently. Which browsers fail on which of your
own test files is itself a result worth writing down, since it decides
whether browser-side extraction is viable or the decoding has to happen on
the server.
