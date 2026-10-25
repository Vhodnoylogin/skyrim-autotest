# SE setup exercised in game (2026-10-26)

The exact 0.3.7 executor and configuration below completed all 21 native smoke
steps in one owned Skyrim SE session: 16 assertions and five observations. This
is tool evidence, not acceptance of an arbitrary mod or all SE configurations.
The shared startup/world-readiness stages ran before scenario actions. A working
HTTP listener or task submission alone was not accepted as gameplay readiness.

| Component | Exercised identity |
|---|---|
| Executor | 0.3.7, source commit `fc2bb1945a71dd28cc82bbe7c47a1b207f4541e4` |
| SkyrimSE.exe | 1.7.104.0, SHA256 `846efccf0c1374d71f892907f46549560f2fcb0a75cb87a3eed438baa0f1402f` |
| SKSE / Address Library | SKSE 2.3.1 / Address Library 13, matching this executable |
| Mod Organizer2 | 2.5.2, separate SE installation and copied profile |
| DevBench | 1.32 compatibility fork and modern CommonLib recipe in [modern SE build](devbench-modern-se.md) |
| DevBench DLL | SHA256 `665d71e91390aae754cf1296dd8318d58fafee45da92f2d51cc9488a9658c512` |
| Initial world | Declared `QASmoke`; Realm of Lorkhan 4.2 was enabled |

The independently extracted portable ZIP used for this run has SHA256
`de469eb96544e2c3662af711f67dd5df49395bd1a02ec209db3e8bddc1ba93e7`.
The scenario identity is `autotest-20261026-se037-repair-2`, native run
`20261026-010703-fb817d`. Generated raw evidence remains external to source Git.
Later documentation changes do not change that frozen package's identity.

## Prepare the provider configuration

1. Use a separate SE MO2 instance, Bridge port/token and runtime directory. Acquire
   the dependencies through the documented recipes; no DLL, SDK, game, save or
   third-party archive is shipped in this repository or agent kit.
2. While the installation is idle, identify and copy the actual winning
   `SKSE/Plugins/devbench/config.json` to an external preparation directory. Keep
   every existing setting, changing only `alwaysActive` to `true` and, to match
   this smoke's diagnostics, `logLevel` to `debug`. Never replace the file with
   a guessed minimal object or edit installed configuration during a run.
3. Hash the generated file and include it in the external runner configuration:

   ```json
   {
     "staged_plugins": [
       {
         "source": "C:/TestBench/se/prepared/devbench-config.json",
         "destination": "SKSE/Plugins/devbench/config.json",
         "sha256": "<actual SHA256 of the prepared file>"
       }
     ]
   }
   ```

   This is a fragment to merge into the existing configuration. The ordinary
   staging mechanism snapshots overwrite's prior file, verifies the source
   hash, stages the copy and restores the original bytes or absence at cleanup.
   The source MO2 profile remains unchanged. The executor separately prepares
   `General/bAlwaysActive=1` in both copied-profile INIs and archives/removes that
   temporary profile at completion.
4. Retain a common-tool assertion that DevBench `inspect.state` actually reports
   `alwaysActive:true`, followed by world readiness and actual action outcomes.
   The first candidate with only the copied INI values did not complete its
   task probes. The second with the staged provider setting completed this
   smoke while `windowFocused:false`; this does not establish that every game
   operation or desktop-input path can work without foreground focus.

`init --edition se` generates paths/examples only. It does not install this
provider, discover the winning configuration, or generate the staged file.
Keep provider/configuration pins in the platform attempt, not in mod orders.
Within the owner's project, Polygon alone admits and operates game sessions.
On another machine, an AI agent must still establish the owner's scope, exact
dependencies, exclusive process ownership and restoration before running.

## Measured scope and retained limits

The run loaded the declared world and verified heading 45, float 3, boolean true,
and the actual string array `["se037a","se037b"]`. An owned 1500 ms W input moved
the player approximately 141.84 engine units horizontally, with released-key
readback afterward. The stock inventory menu really opened and closed, followed
by verified playable-world state. The game closed normally, all owned processes
ended, protected files were restored, and the copied profile was archived and
removed from MO2's normal list.

This does not qualify VR, native New Game UI, Root Builder or reusable SE
profiles. RaceMenu, UIExtensions, OBody and SKEE were not installed or exercised.
No physical contacts, rendered screenshots, save/load lifecycle, float-array
VM calls or arbitrary mod behavior were established by this smoke.

DevBench already supplies game commands, state, Papyrus calls and scenarios.
This executor's contribution is the surrounding complete owned session:
prepared isolated profile, common startup/readiness, actual outcome assertions,
durable evidence, independent recovery and verified restoration. It does not
replace those existing game-control interfaces.
