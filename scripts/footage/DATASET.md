# Attack footage dataset

Recordings of farming attacks are kept as training data for (a) playing the game
and (b) predicting where troops walk after they are deployed.

## Where the files are

Storage root: `/Volumes/T7/coc/attack-footage` on the **Mac mini's** external T7
drive. Connect with `ssh mini` over Tailscale; the laptop does not have a local
mount at that path. See [MINI_SERVER.md](MINI_SERVER.md) for server roles and
the uploader migration. Raw footage stays on external storage or Drive.

| Path | Meaning |
| --- | --- |
| `incoming/<recordingId>/` | Written by the recorder. Complete once `meta.json` exists. |
| `uploaded/<YYYY-MM-DD>/<recordingId>/` | Moved here after a verified Drive upload. Local copies are kept. |
| `upload-log.jsonl` | One line per uploader action (`uploaded`, `verify_failed`, `upload_failed`, `quota_stop`, `abandoned`, `remote_unavailable`, `move_conflict`, `move_failed`). |
| `index.jsonl` | One row per recording, rebuilt by `dataset_index.py`. |

On Drive: `coc-gdrive:coc-attack-footage/<YYYY-MM-DD>/<recordingId>/`, where the date is the UTC date in the id.

`recordingId` is `<UTC yyyymmddThhmmssZ>-<raid label>`, for example `20261103T224512Z-r566`.

## Files in each recording

- `video.mkv`: H.264, 1280x960, variable frame rate up to 15 fps.
- `events.jsonl`: one JSON object per line. Each has `t` (host ms since the Unix epoch) and `type`.
  - `batch`: `actions` is a list of `{kind, label, point, issuedAtMs?}`. `kind` is one of `select`, `spawn`, `spell`, `ability` or `ui`. `point` is `[x, y]` in 1280x960 screen pixels.
  - `damage`: `damage` is the destruction percentage read from the HUD.
  - `cutoff`: the 50% cutoff watcher's `status` and `damage`.
  - `note`: free text, for example the start and stop markers.
- `meta.json`: written last and atomically. Holds `recordingId`, `raid`, `startedAtMs`, `endedAtMs`, `videoStartPtsUs`, `videoStartHostMs`, `frames`, `bytes`, `durationMs`, `size`, `controller`, `stopReason`, `cutoff`, and `opponent`, `loot`, `percent` and `stars` when known.

A folder with no `meta.json` is still being written. After 2 hours with no file changes it is counted as `abandoned`: it is logged once and left in place.

## Lining up video time with events

Video and events use different clocks:

- **Video PTS** in `video.mkv` start at 0 on the first key frame. The absolute device capture time of that frame is `meta.videoStartPtsUs` (device clock, in microseconds).
- **Events** use host wall-clock time `t` in ms.
- `meta.videoStartHostMs` is the host time when that first video packet arrived.

So:

```
video_ms(event)   = event.t - meta.videoStartHostMs
host_ms(frame)    = meta.videoStartHostMs + frame.pts_seconds * 1000
```

`videoStartHostMs` is an arrival time, so it lags the true capture time by the stream latency (typically tens of ms). For tighter alignment, use the `capturedAtMs`/`frameId` fields on `damage` events to estimate the offset. Events with a negative `video_ms` happened before the first key frame.

## index.jsonl row schema

| Field | Type | Notes |
| --- | --- | --- |
| `indexVersion` | int | Currently 1. |
| `id`, `raid`, `date` | str | `date` is the UTC `YYYY-MM-DD`. |
| `state` | str | `uploaded`, `pending_upload`, `recording` or `abandoned`. |
| `uploaded` | bool | |
| `remotePath`, `uploadedAt` | str or null | From `upload-log.jsonl`. |
| `localPath` | str | Relative to the footage root. |
| `startedAtMs`, `endedAtMs`, `hostDurationMs` | int | Host clock. |
| `videoDurationMs`, `frames`, `videoBytes`, `folderBytes`, `size` | | |
| `videoStartPtsUs`, `videoStartHostMs` | int | The clock mapping described above. |
| `opponent`, `loot`, `stars`, `stopReason`, `recordError` | | Copied from `meta.json` when present. |
| `finalPercent`, `finalPercentSource` | number, str | Source order: `meta.percent`, `meta.cutoff.damage`, the last `cutoff` event, then the last `damage` event. |
| `deploys` | list | One entry per `spawn`, `spell` or `ability` action: `{kind, label, point, hostMs, timeSource, videoMs, batchId, order}`. `timeSource` is `issuedAtMs` when the action carried one, or `batchEvent` when the batch's `t` was used instead (coarser). |
| `damageCurve` | list | `{hostMs, videoMs, percent}` from each damage event. |
| `cutoff` | object or null | The last cutoff event. |
| `eventCounts`, `actionCounts` | object | Counts by event type and by action kind (including `select` and `ui`). |
| `badEventLines` | int | Lines that did not parse, such as a partial last line. |

## Using it for training

- **Troop path prediction:** each `deploys` entry gives a spawn point and a `videoMs`. Take frames from `videoMs` onward and track the units. Pair this with `damageCurve` to see which buildings fell.
- **Playing:** `(frame at videoMs, action kind, label, point)` gives a state-action pair. `finalPercent` and `loot` give the outcome.
- `ability` points are hero-button taps, and `spell` points can lie inside the base. Only `spawn` points are ground deployment positions.

For the proposed path from these recordings to three-star decision-making,
including quality checks and the limits of 50% cutoff data, see
[TRAINING_PLAN.md](TRAINING_PLAN.md).
