Corpus Version: RRI Swarm Corpus v1.0
Sessions: 55
Date Range: 2025-12-28 to 2026-02-26
Duration: 61 days
Unique Session Dates: 20
Total Size: 3,223,276 bytes (3.1 MB)

Schemas:
  - raccoon_YYYYMMDD_HHMMSS.json          (15 files, early format)
  - raccoon_v3_YYYYMMDD_HHMMSS.json       (7 files)
  - raccoon_loop_YYYYMMDD_HHMMSS.json     (31 files)
  - sovereignty_loop_*_YYYYMMDD_HHMMSS.json (2 files)

De-duplication completed: 2026-02-26
Duplicates removed: 11 (8 copies across rri_server + RRI_OS_Backup, 3 originals from Anansi/Raccoon Outputs)
Files rescued and renamed: 3 (swarm_* -> raccoon_* from Anansi/Raccoon Outputs)
Files added to canonical: 1 (raccoon_20260108_040623.json from local only)

Exclusions:
  - raccoon_council_test_emotion_map.json (prosody TTS artifact, not a swarm session)
  - Welcome to the swarm_annotated.json (annotated transcript, not a swarm session)

Verification Audit: 2026-02-26 (Claude Code, Opus 4.6)
  Numbers verified against: Google Drive /Logs/ canonical directory
  Method: MD5 checksums on all 55 files (all unique, zero collisions)
  Delta from pre-cleanup: 11 duplicates removed, 4 files consolidated into Logs
  Prior count error corrected: reported as 52, verified as 55 (raccoon_loop_ miscounted as 28, actual 31)

Freeze Protocol:
  - No edits to this dataset after 2026-02-26
  - No retroactive renaming
  - No silent additions
  - New sessions go to Logs_v2_live/
