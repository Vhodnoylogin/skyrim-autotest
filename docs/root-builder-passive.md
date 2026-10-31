# Passive Root Builder presence in SE — unqualified source candidate

This explicit opt-in permits the audited Root Builder 5.1.1 package to be present
without deploying root files. Default SE refusal and the separate VR copy-mode
lifecycle remain. No third-party source is patched or executed by this module.

The pinned source's launch/finish hooks use native `organizer.pluginSetting`:
`redirect=false` prevents redirection, and `autobuild=false` prevents both build
and clear. UI initialization separately calls migration, so an existing explicit
`migrated=true` is mandatory. File mappings can consume BuildData independently;
any `BuildData.json` anywhere below the Root Builder data directory is refused.

All configuration fields below are mandatory. Text pins are placeholders:

```json
"root_builder_passive": {
  "mode": "se-passive-5.1.1",
  "settingsProof": "cold-portable-native-ini/1",
  "pluginTreeSha256": "b1c2ae18837b625016a125d7e8897d6f7b73016bef6d64ddd398c7643b898e9f",
  "dataTreeSha256": "EXACT LOWERCASE HASH OF root_builder._digest(root_builder._tree(DATA_ROOT))",
  "loaderSha256": "EXACT LOWERCASE PHYSICAL skse64_loader.exe SHA256",
  "mo2ExeSha256": "EXACT LOWERCASE NATIVE PORTABLE ModOrganizer.exe SHA256",
  "mutableGameFiles": ["Debug.log", "d3dx9_42.log"]
}
```

Data root is exactly `<mo2>/plugins/data/RootBuilder`, including other-game/tool
backups. No managed subset is guessed. The existing bounded inventory refuses
links/special mutable files rather than silently following them. Existing
`copyfiles=**`, `linkfiles=` and `usvfsfiles=` must already be explicit. SKSE must
exist physically and satisfy the ordinary registered SE loader contract.

Only the exact portable MO2 executable/`ModOrganizer.ini` with `portable.txt` is
supported. No existing MO2/game/VR process is taken over, even for an idle
restart. VR/root-deployment/borrowed/reusable policies cannot be combined. Source
and actual copied profiles must enable no mod with a Root directory; overwrite
Root must be empty, and staged Root files are forbidden.

Before the first generic setup write, the complete passive recovery record is
durably saved, including the pinned contract and `write-barrier` phase. Recovery
therefore retains the same drift and alias checks if later setup fails before
settings preparation. Settings preparation occurs after ordinary durable
snapshots and before MO2 startup. The original INI must already have its verified ordinary snapshot. All existing data
files are additionally snapshotted as protected review evidence. Only two local
`[Plugins]` values are then staged: `RootBuilder\autobuild=false` and
`RootBuilder\redirect=false`. DEFAULT inheritance, ambiguous section/key aliases
and edits of matching names in other sections are refused/avoided.

The proof is explicitly **cold native INI**, not a live `pluginSetting` API
readback: the final full INI hash is recorded before the exact owned MO2 process
birth; its Bridge boot/instance/profile paths must match. Before SKSE, both false
values and the full INI bytes must still match, and package/data/static-root
inventories must be unchanged. Startup rewriting the INI causes an honest refusal
before game launch. It does not authorize weakening this proof. This exact source
candidate still needs independently reviewed native qualification.

Legitimate game-root logs are explicit exceptions, never wildcard ignores.
Each named root-level `.log` in `mutableGameFiles` must also be in `extra_files`,
so ordinary recovery restores its original bytes or absence. Other non-Data root
files/directories are static. Static executables, plugin source and Root Builder
data cannot enter generic extra-file restoration.

After all owned processes end, a passive precheck validates protected inventories
and every generic restore destination before any ordinary recovery write. A
partial setup uses this same precheck. Ordinary recovery restores the exact original
INI and declared logs. Protected data snapshots are not blindly copied over an
unexpected build. Package/data/static-root drift keeps restoration incomplete
for review; no automatic root repair, cache clearing or retry follows. Partial
setup retains its durable intent and backups for the same recovery route.

```text
python -m unittest discover -s tests -p test_root_builder_passive.py -v
```

Synthetic checks and doctor installation checks do not qualify effective settings,
real Root Builder inactivity, engine startup or native restoration.
