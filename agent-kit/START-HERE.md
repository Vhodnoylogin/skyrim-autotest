# Skyrim test kit for any AI agent

Give the agent this extracted archive, `PROMPT.txt`, a description of the mod,
and an external configuration appropriate to the actual game. The agent needs
Windows file/process/command access; no particular AI vendor or chat API is used.
Python3.11+ is acquired separately. This kit contains our source and instructions,
not Skyrim, MO2, SKSE, DevBench, drivers, models or private saves.

1. Read `PROMPT.txt` and `AGENTS.md`. Establish the actual requested scope.
2. Choose **SE** (Skyrim Special Edition/AE executable) or **VR** explicitly:

   ```powershell
   python C:/Tools/skyrim-test-kit/run.py init --edition se --directory C:/TestBench/se
   python C:/Tools/skyrim-test-kit/run.py init --edition vr --directory C:/TestBench/vr
   ```

   Fill paths in the created external config. Use different MO2 installations,
   profiles, tokens, Bridge ports and runtime directories for different games.
   SE never builds/installs a VR driver. Both targets use the same exclusive
   session barrier and refuse existing games/VR sessions.
3. Read `docs/toolchain-refresh.md`. Stock DevBench1.32 is not a drop-in readiness
   provider: the narrow compatibility candidate must be built/qualified separately.
   Acquisition recipes and known hashes are in `dependencies.json`.
4. Describe relevant mod behavior in `test-plan.example.json`, save the edited
   plan externally, then run:

   ```powershell
   python C:/Tools/skyrim-test-kit/run.py review-plan --plan C:/TestBench/plan.json --output C:/TestBench/plan-review.json
   ```

   Exit2 means invalid/incomplete planning, not a game crash. Review weighting,
   behavior omissions and oracles; the script cannot judge the mod's design.
5. Prepare an assertion-bearing scenario using `docs/scenarios.md`. The generated
   SE QASmoke example proves only basic tool/world access, not the tested mod.
   Supply subject actions and actual game-observed outcomes. SE New Game UI is
   unqualified; choose a declared cell or authorized hash-pinned ESS/SKSE pair.
6. Run config-check/preflight, then one authorized run, inspect the final evidence
   and verified restoration. VR additionally needs the pinned external owned
   physical adapter. Changing between targets does not waive any safety check.
7. In this owner's project Polygon operates game sessions and mod chats analyze
   their results. Read the separate Dashboard contract if that orchestration is
   present. Other machines can use the standalone executor; no chat addresses or
   machine-specific paths are embedded in this kit.

Full command reference, supported boundaries and recovery are in README and docs.
Source/offline tests do not establish live acceptance of a new game/provider build.
