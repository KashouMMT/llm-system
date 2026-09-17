# Video frames w/ ffmpeg — build notes

STATUS 2026-09-16 · PROPOSED, NOT BUILT · impl plan for TODO §12 phase 7 (7a–7h)
Decisions live in `Recycling_Estimator_TODO.md` §11a/§11b. Not re-opened here.
Compact by design — notes for context restore, not a document.

## Repo contradicts TODO (3)

1. **ffmpeg NOT in image.** `deploy/Dockerfile` = python:3.14-slim + pip only.
   Need apt layer, ~+300MB. Rejected: imageio-ffmpeg (30MB but NO ffprobe),
   static build (unsigned host). Dev box (Windows, native) needs it too →
   `winget install Gyan.FFmpeg`; extractor must `shutil.which` + clear error.
2. **7e manifest text impossible.** `attachment_manifest.py` is shared/sent
   regardless of loaded plugins; prod excludes recycling → naming `/recycle`
   there is false. Split: core says "cannot watch video" only; command pointer
   → new `app/plugins/recycling/plugin_prompt.txt` (+ `system_prompt=` in
   `__init__.py`).
3. **Video in core = 2nd prod decision.** Type allowlist is core, consumer is an
   excluded plugin → prod accepts 300MB videos it can't use. Accepted, not
   fixed. Per-plugin content types = machinery not worth it for one family.

## Stack

ffmpeg(apt, subprocess) · ffprobe(plugin only, never upload path) ·
`asyncio.create_subprocess_exec` · Pillow `ImageFilter.Kernel`+`ImageStat`
(Laplacian var = blur metric, no cv2/numpy) · `tempfile.TemporaryDirectory`
NEW PY DEPS: none. NEW SYS DEPS: ffmpeg.
NOT taken: opencv, numpy, ffmpeg-python, imageio-ffmpeg.

## Path

browser → nginx(`proxy_request_buffering off`) → handler(sniff 8KB → branch)
→ video? `write_stream` capped mid-stream : existing bytearray path → files row
→ `/recycle scan_video` → `temporary_path` → ffmpeg(`-skip_frame nokey`, scale
1024) → Pillow score → bucket-select → `detect_items_bytes`(N frames, 1 call)
→ `merge_runs` → `resolve` → md + json attach

Right of `detect_items_bytes`: **unchanged**. Left of handler: host-app work.

## Design calls not in TODO

- **`FileStorage.temporary_path(key) -> AsyncCM[Path]`.** ffmpeg needs seekable
  file; `read()` gives bytes → 150MB through RAM to write a copy of a file
  already on disk. Local yields real path, copies nothing. S3 later downloads +
  deletes. Contract = "temporary local copy", NOT "where it lives".
- **Frames not stored.** Temp dir → memory → gone. §11b retains raw video *so
  extraction can be re-run*; stored frames = cache of a cheap reproducible
  derivation, invalidated by next strategy change. Revisit once: review UI
  (phase 5) evidence thumbnails.

## Build order (reordered: 7g before 7e)

| # | was | work | verify |
|---|---|---|---|
| 0a | — | **DONE** ffmpeg on dev box (winget Gyan.FFmpeg, 9.0.1-full) | `ffmpeg -version` |
| 0b | — | DEFERRED ffmpeg apt layer in Dockerfile — prod only, user's call: prove local first | — |
| 1 | 7a | **DONE** `write_stream`, `temporary_path` + quota → 1 GB | smoke-tested: stream, temp path, abort leaves no `.part`, missing key raises |
| 2 | 7d | **DONE** video types in `detect.py` | real ffmpeg-made mp4/mov/mkv/webm + negatives, all pass |
| 3 | 7b | **DONE** per-type caps + streaming branch; `MAX_ATTACHMENT_BATCH_BYTES` 100→400 MB (was a hidden blocker: non-admin could upload a video, then fail to send it) | TestClient: head-break-then-continue on Starlette stream byte-identical; over cap → 413, no `.part` |
| 4 | 7c | **DONE (conf only, not deployed)** nginx 320m + `proxy_request_buffering off` | `nginx -t` on deploy |
| 5 | 7g | **REDIRECTED 2026-09-16 by user: video is a baseline chat attachment, not plugin-only.** Built `app/utils/video_frames.py` (core, NOT `pipeline/frames.py`) + `chat_service._build_video_blocks` + manifest video branch (`video_frames_shown`) + UI 500MB video check/accept types. Chat flow: attach → stream to storage → ffmpeg → 12 frames as image blocks → chat model. `/recycle scan_video` NOT built yet — will just call core `extract_frames`. Video cap 300→500MB, nginx 520m. ffmpeg now a CORE dependency (reverses "core must not depend on plugin's binary" — no longer plugin's) | real 1080p clip → 12 frames 1024×576 ~300KB; bad file → clean error; tsc clean. Rotation NOT verified (`rotate=` metadata ignored by ffmpeg 9 muxer) |
| 6 | 7e | manifest, plugin_prompt, UI | attach video, no /recycle |
| 7 | 7h | `scan_image` → `scan` (alias 1 rel.) | — |

7g before 7e: once the command works the path is testable by hand, and UI work
is then informed rather than guessed.

## Step notes

**0** apt layer before pip layer (requirements change must not re-run apt):
`apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*`

**1** `local_storage.py`: extract `_new_key(ext) -> (key, Path)` shared by both
writers. `write_stream(chunks, *, extension) -> (key, bytes_written)`: mkdir via
to_thread, write `.part` w/ `to_thread(handle.write, chunk)` per chunk, atomic
`.replace`, `except BaseException: unlink(.part); raise`. Iterator raising IS
the cap mechanism — cleanup depends on it. `temporary_path` =
`@asynccontextmanager`, `_resolve` + `is_file()` check + yield.

**2 DONE** `detect.py`: `VIDEO_MP4/QUICKTIME/MATROSKA` (**no** `VIDEO_WEBM` —
sniffer can't produce it, .webm shares the EBML header and reports as
matroska), `VIDEO_CONTENT_TYPES`, extensions mp4/mov/mkv. Sniff after PDF,
**before** text decode: `data[4:8]==b"ftyp"` AND `8 <= box_len <= 1024` →
quicktime if `data[8:12]==b"qt  "` else mp4; `\x1a\x45\xdf\xa3` → matroska.
Box-length bound is required: video runs before the text decode, so without it
a text file reading `"abc ftyp…"` at offset 4 is stolen from the text branch.
Unknown brand → mp4, don't reject (untrained customer, §1). **No ffprobe here**
— core must not depend on an excluded plugin's binary.
Verified vs real ffmpeg output: mp4 brand `isom` box 0x20, mov brand `qt  `
box 0x14; negatives (plain text, cp932, json, the ftyp-at-4 text, garbage) all
stay non-video.
⚠ PATH: a process started *before* the winget install does not see ffmpeg.
Restart the shell that runs the app, or `shutil.which` returns None.

**3** `UPLOAD_MAX_BYTES_VIDEO` default 300MB. Handler: `stream =
request.stream()` ONCE (Starlette refuses a 2nd call), buffer head to
`_SNIFF_BYTES=8192`, `if not head: 422` (empty body else sniffs as text),
provisional sniff → picks branch+cap only. Non-video branch **re-sniffs full
body** — else a file clean for 8KB then binary at 20KB gets accepted, a
regression. Helpers `_rejoin(head, rest)`, `_capped(chunks, limit, status,
detail)` raising inside the iterator. Daily quota folded into the cap
(`min(limit, remaining)`) instead of checked after — else 300MB lands on disk
before rejection. Status = 413 or 429 by which limit binds.
⚠ `UPLOAD_DAILY_BYTES_PER_USER`=200MB → **1 scan/day/user**. Must move.
⚠ settings comment "request that crosses the cap is still accepted" goes stale.

**4** `client_max_body_size 320m` (> app cap, so app's localized 413 wins);
`proxy_request_buffering off` in the API location block or step 1 bought
nothing.

**5** New `app/plugins/recycling/pipeline/frames.py`:
- `DEFAULT_FRAME_COUNT=12` `_CANDIDATE_LIMIT=200` `_FFMPEG_TIMEOUT_SECONDS=300`
- `_EXTRACTION_LOCK = asyncio.Semaphore(1)` — ffmpeg saturates cores, box also
  serves SSE. §11b claims "serialised"; this is what makes it true.
- `Frame(index, data, sharpness)` frozen dc. sharpness comparable within one
  video only.
- ffmpeg argv: `-nostdin -hide_banner -loglevel error -skip_frame nokey`
  (INPUT opt → non-keyframes never decoded, 10-50× cheaper) `-i src`
  `-vf scale=w=1024:h=1024:force_original_aspect_ratio=decrease` (= vision.py
  `MAX_IMAGE_EDGE` → Pillow thumbnail becomes no-op; also caps 4K memory)
  `-fps_mode passthrough` (VFR phone video; CFR would fabricate dup frames)
  `-frames:v 200 -q:v 3 out/f_%04d.jpg`. Rotation: auto (display matrix applied
  unless `-noautorotate`).
- `wait_for(process.communicate(), 300)`; on timeout kill+wait; nonzero rc →
  `ExtractionError` w/ last 400 chars of stderr only.
- `_LAPLACIAN = ImageFilter.Kernel((3,3),(0,1,0,1,-4,1,0,1,0),scale=1,offset=128)`
  offset only keeps negatives in 8-bit; shifts mean, not variance.
  `_sharpness`: convert L → thumbnail 320 → filter → `ImageStat.Stat(..).var[0]`.
- `select_frames(candidates, count)`: **sharpest frame per time bucket.**
  Even spacing alone → mid-pan frames (blurred + encoder-starved). Sharpest
  overall → all frames from the one still moment, half the room unseen.
  Buckets by candidate index ≈ time (keyframes roughly even); exact = ffprobe
  PTS, not worth a 2nd subprocess yet.
- Unreadable single frame → warn+skip, not fatal. Zero frames → ExtractionError.

`commands.py`: `_attached_videos` mirroring `_attached_images` (skipped files
reported, never dropped); `scan_video` → `_make_scan_video(client, model,
file_repository, file_storage)` closure. >1 video → refuse (1 recording = 1
room; merging two results is the across-recordings dedup problem nothing
solves). Optional int in `context.argument` = frame count, undocumented knob,
NOT the §12 presets. `scan()`, `render_scan_result()`, `_attach_json()`,
`vision.py` untouched — that's the test of correct scoping.

Stale text to fix same step: stub says "needs OpenCV keyframe sampling"
(reversed by §11b); plugin `README.md` repeats it + points at
`documentation/other/...TODO.md` twice (it's in `documentation/claude/`).

**6** manifest video branch: "You cannot watch video." — nothing about
scanning. `plugin_prompt.txt` names `/recycle scan_video`, says user runs it
themselves, table is the result, don't restate numbers or drop flagged rows.
UI: `ACCEPTED_FILE_TYPES` += video types; `MAX_UPLOAD_BYTES` → per-type lookup.
⚠ **Upload progress needs XMLHttpRequest** — `uploadFile` uses fetch, no upload
progress event; streaming request bodies unsupported in Safari/Firefox. Real
rewrite of that function; largest piece of step 6, why step 6 is last.

## Live test 1 (2026-09-16 18:14) — FAILED, fixed

Upload + streaming OK (8.8MB mp4, `write_stream` logged). Extraction raised
`NotImplementedError` from `asyncio.create_subprocess_exec`: `app/main.py`
forces `SelectorEventLoop` on win32 (psycopg async), and only Proactor spawns
subprocesses on Windows. Earlier scratch test passed because it ran on the
default loop. Fix: `asyncio.to_thread(subprocess.run, …, timeout=)` — any loop,
any OS. Verified under `SelectorEventLoop(SelectSelector())`. RULE: test async
code under app/main.py's loop, not a bare `asyncio.run`.
Turn did not fail — `_build_video_blocks` returned [] and manifest said
"could not be prepared", as designed.

## Live test 2 (2026-09-16 18:17) — PASSED (chat path)

room_1.mp4 9.6s 720p h264, KF every 1.0s → candidates=10 selected=10.
room_2.mp4 6.0s 1080p h264, KF every 1.0s → candidates=6 selected=6.
Both landscape → **rotation still untested**. Extraction ~0.3s, LLM ~4s.
⚠ Pool < DEFAULT_FRAME_COUNT → sharpness selection never ran; clips too short
to exercise it. Real 1–3 min sweep ≈ 60–180 candidates. Don't tune on these.
Reply accuracy (checked vs keyframe contact sheets): good. room_1 desk items
right; "2 monitors, one off" likely = 1 monitor + dark laptop lid (label
double-count, not view dup). room_2: fan, lamp, folding chair, sofa, buckets,
basin, router, headset, Lay's bag all real; mic on boom → "speaker"; person
correctly excluded. Faces visible in frames → sent to LLM (privacy, TODO §13 #7).
Config ⚠: `loaded=[attachments, clock, recruitment, recycling]` — recruitment
NOT excluded; its prompt rides with meguru → system prompt 3448 > budget 3000.

## Capture rules — decided 2026-09-16 (client OK'd guided capture = TODO §13 #6 answered yes)

Users: Japanese, rule-following → strict capture rules are viable, not friction.
Rules: slow steady sweep, no sudden movement; **landscape only** (decided —
wider FOV/frame, more view overlap → better dedup); rotation still handled by
ffmpeg regardless. Rules text home = recycling `plugin_prompt.txt` (+ UI later),
NOT meguru persona → trim persona CAPTURE GUIDANCE to avoid 2 drifting copies.

Frame quality gate (proposed, Pillow only, thresholds = guesses until calibrated
on real sweeps; start extreme-only):
| check | metric | action |
|---|---|---|
| blur | Laplacian var < k × video median | drop |
| black | mean luma < ~15 | drop |
| white/blown | mean luma > ~240 | drop |
| flat/monotone (covered lens, wall close-up) | luma stddev < ~8 or `Image.entropy()` low | drop |
| partial overexposure/glare | % px ≥ 250 > ~25% | WARN only (can't tell glare from window/white wall) |
| lens flare streaks | not cheaply detectable | not attempted |
| near-duplicate (camera parked) | tiny-thumb mean abs diff vs prev kept | drop (tokens) |
Video-level (ffprobe, deterministic): portrait → warn; duration < ~10s → warn;
res < 720p → warn. Usable frames < ~4 → refuse scan w/ reason-specific remedy.
ALWAYS report per-reason counts ("blur 5, dark 2") — command output + chat
manifest line. Never a silent short scan.

## Agentic invoke (future, user goal 2026-09-16)

Plugin exists to put recycling in the agent loop → model calls scan like a tool.
Tension: tool result → model relays → can drop/alter rows (violates
nothing-dropped rule). Pattern already in repo: `generate_rirekisho` — tool
writes artifact to assistant message, returns short confirmation. So tool =
run pipeline → attach deterministic result (JSON + rendered table) → return
compact summary + "full table attached, do not restate numbers".
OPEN design q: deterministic *rendered* table in the message from a tool (today
only commands own the message text).
Guards: file id arg verified vs conversation (read_attachment pattern); identity
from run config; cache result by (file id, pipeline version) so re-calls cost 0.
**Do now in step 5:** handler = thin wrapper over one `scan_video(file) ->
ScanOutcome` service fn → command & future tool can't diverge.
Blur: user wants blurry frames ignored, not sent to LLM. Note: can't know blur
without decoding — keyframe decode is cheap (~0.3s); the saving is LLM tokens.
Impl idea: relative threshold (drop < X% of this video's median Laplacian var;
absolute thresholds vary w/ scene/resolution) + REPORT "N frames skipped as
blurry" + warn if too few remain → never a silent short scan.
Rules must be mirrored in meguru `system_prompt.txt` CAPTURE GUIDANCE (currently
generic) and later in UI.

## Batch 5/5b/5c + video-alone rule — BUILT 2026-09-17, awaiting live test

- **Video-alone rule** (user): 1 video/message, nothing else. Backend =
  `MessageRepository.create_turn` (RETURNING content_type; ValueError → 422,
  tx rollback frees uploads). Frontend = `useAttachments.addFiles` (videoQueued
  / batch check, `isVideoFile` MIME-or-extension since Win gives .mkv no type)
  + separate video button (`bi-camera-video`, `ACCEPTED_VIDEO_TYPES`, no
  `multiple`); paperclip `ACCEPTED_FILE_TYPES` no longer lists video. i18n keys
  `attachVideo`, `attachmentVideoAlone`, `attachmentVideoTooLarge` (en+ja).
- **5b** `extract_frames` now returns `FrameSample(frames, candidates, skipped,
  warnings)` + `.summary()`. Drops: dark mean<16, overexposed mean>240, blank
  stddev<6, blurry < 0.25×median sharpness (median of exposure-OK frames only),
  duplicate thumb(32×18) diff<1.0. Warns: portrait (from decoded frame dims —
  post-rotation), glare >25% px≥250, duration<10s, short edge<720 (ffprobe,
  best-effort). Refuse <4 usable w/ remedy by dominant reason.
  Calibration: real sweeps consecutive-KF diff 25–85, parked 0.0–0.1, testsrc2
  2–3.5 (first try 3.0 dropped 19/30 of synthetic "good" → set 1.0).
  Verified on synthetic good/darkend/blurmid/black/static/portrait + room_1/2.
  Chat path: `_build_video_blocks` → (blocks, note); manifest `video_note`
  appended ("Frame check: … Tell the user") or failure "Reason: … Pass on".
- **5** `runner.scan_video(file, file_storage, client, model, catalog,
  frame_count) -> VideoScanOutcome` = THE shared entry (command now, tool
  later). Command `_make_scan_video`: arg 4–40 default 12; header = summary +
  ⚠ warnings ABOVE table; JSON gains `frame_check`.
- **5c** `recycling/plugin_prompt.txt` (1611 chars): commands exist, model
  can't run them, chat-frame lists ≠ scan result, don't restate table,
  re-read JSON, 6 recording rules. Wired `system_prompt=load_plugin_prompt`.
  meguru CAPTURE GUIDANCE removed.
- Docs: README (plugin prompts para "Three plugins", scan_video, tree), plugin
  README (scan_video row, TODO path other/→claude/).
NOT done: DB-level test of create_turn rule (no test DB) — live test covers it.

## Upload limits collapsed to 2 — 2026-09-17 (user: "too many caps")

SUPERSEDES all earlier cap notes above (per-type video cap 300/500MB, batch
cap 100/400MB, nginx 320m/520m).
- `UPLOAD_MAX_BYTES` 20MB: every non-video file, admin too.
- `UPLOAD_DAILY_BYTES_PER_USER` 1GB, `get_optional_positive_int` ("null"/"none"
  → no limit; blank/unset → default; typo can't disable). Files+video share it.
  Admin/root exempt. ONLY bound on a video (sent alone → ≤ whole allowance).
- REMOVED: `UPLOAD_MAX_BYTES_VIDEO`, `MAX_ATTACHMENT_BATCH_BYTES` (+
  `create_turn(max_attachment_batch_bytes)`, frontend batch-total check,
  `attachmentTooLarge` i18n). Batch cap redundant: each upload already bounded.
- Handler: video limit = sys.maxsize → min with remaining allowance.
- Frontend `MAX_VIDEO_UPLOAD_BYTES` = 1GB mirror of daily default, skipped
  for admin.
- nginx 1100m = also admin's hard ceiling in deploy (none locally).
- 1GB feasibility: `_CANDIDATE_LIMIT` 200→1200 — **200 silently dropped every
  keyframe after ~3 min** (ffmpeg `-frames:v` stops). Timeout 300→600s.
  Worst case ~100MB temp JPEGs. Not measured on a real 1GB file.

## Live test 3 (2026-09-17 12:07–12:33) — PASSED w/ findings

Passed: 1–6, 9–16, 18, 19 (loaded w/o recruitment, no budget warning), 20
(implicitly: chat replies disclaim "not a scan result" + give command/rules).
Not run: 7, 8 (daily limit), 17 (lens covered mid-sweep).
Videos: stable_landscape 960×540 32s → 12/33, warn low-res; pitch_black
1280×720 rot=-90 9.7s → refused "1 of 8 usable, flat colour" (classified
blank not dark — phone noise lifts mean >16, stddev <6; remedy still apt);
stable_portrait 540×960 24s → 12/25, warn portrait+low-res; unstable_rotate
_portrait 540×960 11s → 11/11, 0 blurry. Scan ~25s, extraction ~0.5s.
FINDINGS:
1. **catalog.json `person` row excluded=false** (obs=1, 75kg) → scan listed
   "person ×2, 150 kg" as Collectable. Catalog hand review = real blocker.
   Also consider detection-prompt guard "never list people".
2. **Uniformly shaky video: 0 blurry drops.** → CALIBRATED, absolute floor
   REJECTED. Laplacian var (320px thumb, offset 128) per KF:
   stable_landscape 136–557 med 352; stable_portrait 104–439 med 314;
   unstable 89–337 med 205 (in order 332,171,337,205,162,277,200,89,264,119,
   279); pitch_black 189–269 (noise scores as detail!). Contact sheet: unstable
   frames are mostly SHARP but TILTED/sideways (phone fast shutter); 89 = real
   smeared close-up, 119 = sharp plain white wall + bucket. Metric = texture,
   not sharpness → any floor catching shaky frames also drops sharp plain-wall
   frames (stable_portrait has 104/110). Keep relative only. Real failure =
   tilt → OpenCV pass (Hough horizon). Exposure checks before blur stay
   essential (noise).
3. Video button's picker "All files" accepts an image → treated as normal
   attachment. User: acceptable.
4. stable_landscape scan "computer monitor 3" vs chat reply "two monitors" —
   possible label double-count; unverified.

## Queued AFTER video live test — attachments → core (decided 2026-09-16)

Why: attachments already ~90% core (upload route, `files`, storage, sniff,
manifest, vision prep). Only `read_attachment` (~390 lines) + 12-line prompt in
`app/plugins/attachments/`. No deployment runs without attachments (job-app:
CVs; recycling: photos/video/scan JSON). Plugin status = fake optionality:
excluding it leaves core manifest saying "Call read_attachment" (false) and
breaks recycling's re-read. Rejected alt: everything-in-plugin — `files` +
`FileStorage` used by recruitment + recycling → plugin→plugin dep; needs 3 new
extension points (plugin routes, turn-shaping hook, loaded-plugins endpoint).
Work: move `tools.py`/`prompts.py`/`plugin_prompt.txt` → `app/attachments/`;
`Application` ~L311 always append `read_attachment` beside `load_tools`, its
prompt beside `load_plugin_prompts` (~L325); delete plugin folder; fix
`loader.py` L301 docstring, README tool-plugins section + tree, any
`EXCLUDED_TOOL_PLUGINS` mentions. Retest: PDF read, CSV read, recycle JSON re-read.

## Not built (deliberate)

near-dup pruning between frames (→ cv2, needs measured gap) · `seen_in:[1,3]`
per item (§11a improvement; schema change touches single-image path; do with
review UI) · `fast`/`slow` presets (curve unmeasured; naming fixes a vocabulary
to a guess) · browser-side extraction (§11b: latency opt, "do not build first")
· storing frames · ffprobe in upload path

## Open

| # | q | blocks |
|---|---|---|
| 1 | ~~+300MB image size ok?~~ | ANSWERED yes (docker image, not uploads — user initially misread it as a picture file) |
| 2 | ~~new `UPLOAD_DAILY_BYTES_PER_USER`?~~ | ANSWERED 1 GB, applied to settings.py default |
| 3 | retention duration (TODO §13 #7, client) | **only** 7f. FileStorage is the boundary → steps 0–7 don't wait |
| 4 | ~~run §11a undercount probe before step 5?~~ | DEFERRED by user: working model first, refine on real footage. Risk accepted — undercount is the *invisible* failure (no row appears, agreement stays high, `count_is_unstable` cannot fire), so it will not surface on its own. Re-raise when tuning `DEFAULT_FRAME_COUNT` |
