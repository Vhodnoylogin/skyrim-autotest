# Development entrypoint

Read AGENTS.md and README.md. Runtime uses only the Python standard library.
External dependencies and all generated output must stay outside Git.
Keep worktrees, build directories and logs beneath the configured project workspace,
not in a drive root. On the owner's machine use D:/Skyrim VR Modding/Worktrees
and D:/Skyrim VR Modding/Builds. A short compiler path must still be inside that
workspace. Reconfigure moved CMake/xmake build trees before rebuilding; preserve
historical manifests and record relocation separately.
