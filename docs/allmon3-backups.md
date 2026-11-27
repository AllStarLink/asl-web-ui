# Allmon3 persistent-data backup coverage

WebUI's default include list now also includes these paths when present:

- `/etc/allmon3/favorites`
- `/etc/allmon3/audio` (SQLite metadata/schedules/enable flags and original media)
- `/etc/allmon3/logging` and `/etc/allmon3/logging-nodes.json`
- `/etc/allmon3/announcements.ini`, `/etc/allmon3/speech.ini`, `/etc/allmon3/addons.d`

This supports data from the corresponding optional/proposed Allmon3 features;
it neither installs/enables them nor changes the Logs placement proposal.
Converted caches and `/var/log` history are not added to configuration backups.

An absent list uses these defaults. Only a byte-for-byte copy of the previous
WebUI default is expanded automatically, on the next WebUI backup; its existing
mode/owner are retained. Read-only include-list display previews that expansion.
Any customized list, even a comment-only edit or explicit exclusion, remains
unchanged. Settings and the backup job warn about existing known data paths it
omits. Use the existing include-list editor to add wanted paths, including custom
state paths. Parent-directory coverage is recognized. The saved list is also
used by `asl-backup-menu`; WebUI does not modify that tool or its own defaults.

Stop Allmon3 **at idle** and keep it stopped throughout backup/restore. This
change does not automatically stop it or claim a transactionally consistent
snapshot of a running SQLite database/media set. Install corresponding packages
before restoring, so their service-owned directories already exist. Existing
restore logic retains destination ownership, not untrusted archive ownership;
verify `allmon3:allmon3` ownership and the documented modes before restart.
Inspect restored recording flags, schedules and pending jobs before restarting.
No missing/corrupt-file policy is changed by this coverage fix.

The cloud server limit remains 2,000,000 bytes. Original media can exceed it;
retain an external copy of local archives. Browser imports are capped at 64 MiB;
larger archives require an administrator-managed restore. Do not silently omit
source media to fit a limit. CLI/custom backups still need the same include-list
and quiescence checks.

Tests exercise actual API backup/download/restore with idle SQLite data, both
disabled enable flags, source media, Favorites/Logs settings, configuration,
permissions and ownership preservation, cache exclusion, legacy default upgrade,
and customized-list retention/warnings. Services are simulated; no live station
backup, lifecycle install or RF behavior is claimed.
