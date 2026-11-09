# Mac mini footage server

The Mac mini (`ssh mini`, Tailscale) owns T7 at
`/Volumes/T7/coc/attack-footage`. The laptop is a remote client. Absence of a
local `/Volumes/T7` on the laptop does not establish a storage outage.

## Verified on 2026-11-05

- Tailscale and SSH reach the mini; T7 is mounted there.
- Initial inspection found 107 uploaded recordings and 18 complete recordings
  (r677-r694, 595,776,079 bytes) waiting in `incoming/`.
- The uploader was running on the laptop, whose local T7 path is absent.
- The mini initially had neither rclone nor the uploader service installed.
- Recovery completed: all 18 recordings were copied to Drive; rclone MD5
  verification found 73 matching files and zero differences. Matching source
  snapshots were checked under the uploader lock before moving those folders
  into `uploaded/`. The rebuilt index contains 125 uploaded recording rows.
- Drive recount: **125 videos, 504 files, 4,920,168,566 bytes**. A separate
  four-file check from the mini also passed, excluding macOS sidecars.
- Rclone 1.75.2 and the uploader are installed under
  `/Users/elijah/services/coc-footage`. Compilation, CLI help and plist checks
  pass. Only the existing `coc-gdrive` connection was provisioned over SSH;
  credentials were not printed and other remotes were not copied. Drive quota
  access from the mini succeeds. The unused fresh OAuth flow was stopped.
- The user approved automatic uploads at login and every two hours. The first
  scheduled run failed with macOS `Operation not permitted` on T7. TCC logs
  identified the shell wrapper as the responsible process. The prepared plist
  now launches `mini_service.py` directly through Python, so the user can grant
  the interpreter drive access without granting it to a general shell.
- The corrected plist is installed in `~/Library/LaunchAgents/` but unloaded
  pending the user's macOS drive-access grant. Do not report scheduled uploads
  as working until a new launchd run succeeds after that permission change.
- At inspection, T7 had approximately 374 GiB available.

## Roles and data path

1. The game controller retains its sole-owner rules and captures recordings.
2. Completed recordings arrive on the mini's T7. Publish `meta.json` last so
   incomplete transfers cannot be treated as complete recordings. A future
   remote recorder/transfer integration needs an explicit handoff with the
   controlling session; moving T7 alone does not redirect a laptop recorder.
3. The mini verifies and uploads complete folders to
   `coc-gdrive:coc-attack-footage/<UTC date>/<recording ID>/`.
4. Only verified uploads move from `incoming/` to `uploaded/` on T7. Originals
   are preserved. Catalog and offline data work run on the server or cloud.
5. The laptop inspects counts, logs and health through SSH over Tailscale.

Use existing SSH access. No public ports, SMB share or persistent tunnel is
needed. Drive credentials live in the mini's normal private rclone configuration.

## Prepared uploader

Code location on mini: `/Users/elijah/services/coc-footage`.
`mini_service.py` runs the existing `upload_footage.py`, `footage_common.py` and
`dataset_index.py`. The staged `com.elijah.coc-footage-upload.mini.plist` runs at login and every
7,200 seconds, preserving the existing two-hour cadence. It logs missing-volume
and upload errors and refreshes the index after each uploader pass.

Persistent activation was explicitly approved on 2026-11-05. The mini uses the
existing authorized Drive connection; `/opt/homebrew/bin/rclone about coc-gdrive:
--json` verifies access without exposing credentials. A user LaunchAgent starts
after that user logs in; this is not a pre-login system daemon.

### Remaining macOS permission

The user must allow Python access to removable volumes in Files & Folders, or
add and enable its app in Full Disk Access if no narrower toggle is available:

`/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app`

System Settings and the app's Finder location were opened on the mini. Do not
edit TCC databases or reroute the scheduled process through SSH to evade the
denial. After the user confirms the permission change, bootstrap the corrected
plist, verify its exit code/log and confirm the two-hour interval. Remove the
obsolete laptop job after that server run succeeds.

Rclone warns that its shared Google client ID is being retired. Plan a separate
client-ID migration; preserve access to the existing Drive dataset when changing
OAuth app identity and scopes.

## Backlog recovery without moving credentials

The laptop can use its existing Drive authorization and rclone's SFTP backend
over `ssh mini` to stream a fixed list of complete recordings from T7 to Drive.
No raw video needs to be staged on the laptop. Use normal SSH host-key checking,
copy only the snapshot's files, verify the cloud copy, and finalize the T7
folders under the uploader lock only if their source snapshot still matches.

Recovery inventory and receipts are kept under
`session_watch/remote_storage/`. A copied folder is not considered verified
until its rclone check succeeds.

## Laptop recorder transfer — 2026-11-05 16:20

User approved "yes fix recording to the mini". The laptop watcher records to
`~/coc-footage-outbox/incoming/` and `scripts/android_agent/footage_shipper.py`
moves complete folders to this T7 over `ssh mini` (`.transfer/<id>` → checksum
→ rename into `incoming/<id>`). Laptop copies are removed only after a matching
SHA-256 check. End-to-end test against a scratch folder on T7 passed and the
scratch folder was removed.
