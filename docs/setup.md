# Prepare an independent SE or VR installation

`setup` creates a filled, versioned external configuration from one explicit JSON
specification. `doctor` checks acquisition and preparation without contacting a
running game, MO2, an API, a queue, SteamVR or a microphone. Both editions use the
same command and schema; keep their configurations, runtime directories, MO2
instances and Bridge ports/tokens separate.

```powershell
python C:/Tools/skyrim-autotest/run.py setup --spec C:/TestBench/se-setup.json
python C:/Tools/skyrim-autotest/run.py doctor --spec C:/TestBench/se-setup.json
```

The module entrypoint is also available:

```powershell
python -m skyrim_autotest.setup install --spec C:/TestBench/se-setup.json
python -m skyrim_autotest.setup doctor --spec C:/TestBench/se-setup.json
```

Start from [the example specification](../agent-kit/setup-spec.example.json).
Supply your actual absolute paths and hashes; its sample locations and zero
hashes are illustrative. `setup` does not discover an MO2 instance or substitute
personal paths. An existing `init` template is preserved; select a new
`config_directory` for setup.

## Explicit schema 1

| Field | Meaning |
|---|---|
| `schemaVersion` | Integer `1` |
| `game_edition` | Required `se` or `vr`; no inferred/default edition |
| `config_directory` | New absolute external directory; its parent must exist |
| `paths` | Actual runner paths listed below |
| `bridge_port` | Explicit separate integer port, 1–65535 |
| `required_mods` | Actual required MO2 mod directory names; existence is checked, activation is a later operator action |
| `dependencies` | Acquired external files with id, absolute path, actual lower-case SHA256 and official HTTPS source |
| `provider` | Exact DevBench dependency name, full configuration pin and native capability-manifest pin |
| `destination_allowlist` | Exact permitted overwrite-relative staged destinations, including `SKSE/Plugins/devbench/config.json` |
| `staged_plugins` | Optional runner staging declarations with absolute `source`, `destination`, `sha256` |
| `configuration` | Optional current runner settings such as `se_new_game_ui`; path/identity/port/mod/staging fields stay in their dedicated fields |
| `command_bus` | Optional loopback API URL and absolute `token_path`; creates a usable channel configuration and neutral adapter reference |

`paths` requires `runtime`, `game`, `mo2`, `mo2_exe`, `mo2_ini`, `mods`,
`profiles`, `overwrite`, `bridge_token` and `skse_logs`. VR additionally requires
`openvr_paths`. Optional current runner paths, including `fixture_dir`, may also
be supplied. Every supplied path is absolute. Newly generated runtime/configuration
and private command-API credential paths must stay outside Git and the distribution;
runtime and configuration must stay outside the live game/MO2 directories.
Existing explicitly pinned game/MO2/provider/dependency inputs may have an existing
Git ancestor: setup only reads/hashes them and does not acquire, modify or commit
those files. This exception does not permit generated output or downloads into
that checkout. Links and Windows
junction/reparse points at these paths or their ancestors are refused.

The `mo2_ini` path selects the instance explicitly, including instances whose
configuration lives separately from the executable. Doctor reads the registered
SKSE executable and checks its loader, game working directory and absence of
hidden arguments. Existing `Settings` paths for mods/profiles/overwrite must
match the declaration; `%BASE_DIR%` is resolved from this INI's directory. Setup
never edits the INI or completes MO2 onboarding. Both editions require one
registered `SKSE` entry; SE checks `SkyrimSE.exe`/`skse64_loader.exe`, VR checks
`SkyrimVR.exe`/`sksevr_loader.exe`.

Explicit VR `configuration.root_builder` and `paths.root_builder_data` select
only the audited `copy-5.1.1` policy from [the Root Builder contract](root-builder.md).
In that mode the `skse` dependency must pin the exact
`mods/<loaderMod>/Root/sksevr_loader.exe` source, and doctor verifies all three
source-bundle hashes/PE headers, the audited installed package fingerprint and
the existing exact game/version cache/backup with no active BuildData. The
registered executable still targets the eventual game-root loader. That loader
may legitimately be absent before owned autobuild: doctor reports source
readiness and `deployment:pending-owned-autobuild`. It does not copy a loader or
create/repair a cache. The setup spec does not select a source profile; the later
separately admitted `preflight --profile NAME` must verify that the exact source
mod is enabled uniquely, wins conflicts, and satisfies the complete settings and
restoration contract. Ordinary VR without explicit Root Builder continues to
require the physical game-root loader. SE rejects this policy.

## Acquire and pin dependencies separately

Use [the dependency catalogue](../dependencies.json) and its source/build recipes.
No game, SKSE, MO2, provider DLL, SDK, driver, model, save or third-party archive is
included in the release. Acquire licensed tools/assets yourself through their
permitted sources. Setup performs no downloads, privileged installers, game/MO2
installation, mod activation, launch, recovery or queue operation. Installation
and later game execution require the owning operator's exclusive live-session
workflow.

Each dependency has `id`, `path`, `sha256`, `source`, optional `kind` (`file`,
`pe`, `header`) and optional boolean `required` (default true). Sources are HTTPS
acquisition URLs without embedded credentials, query parameters or fragments.
Use an official public source page rather than a temporary signed download URL.
The path selects the actual acquired file, not the URL. Doctor recomputes its
hash. Executables/native DLLs require AMD64 PE32+ headers; SDK headers require a
textual C/C++ header. These checks cannot prove compatibility with every game
runtime or execute/qualify a build.

Mandatory IDs are `game`, `skse`, `mo2`, `mo2-api-bridge`, `devbench` and
`address-library`. The first three pins must match the declared game executable,
edition-specific loader and MO2 executable. VR additionally requires `steamvr`,
`physical-driver` and `openvr-header`; SE has no VR dependency requirement.
Additional subject/provider dependencies can be declared with their own IDs.
The physical-driver pin records the separately built owned adapter, not a stock
manual-control driver assumed to implement the executor's protocol. Runtime
preflight independently verifies the actual driver build manifest and protocol.

Missing declarations/files, wrong hashes/headers, missing required-mod
directories and invalid instance settings produce actionable checks and
`preparationReady:false`. A valid full provider configuration is required before
setup publishes a bundle. Other missing dependencies can be acquired afterward:
setup records their missing state and exits `2`, and doctor evaluates their
current state on every call. The original acquisition report stays immutable;
the fresh doctor result is the current assessment. Neither acquired files nor
mod-directory existence prove enabled mods, actual loaded provider modules,
native runtime capability or live readiness.

## Preserve and prepare the provider configuration

`provider.artifact` is `devbench`. `provider.configuration` is a pin object
`{path, sha256, source}` for the actual winning full
`SKSE/Plugins/devbench/config.json`. Setup creates an external copy that preserves
all settings and sets `alwaysActive:true`. It adds the copy and its computed hash
to the runner's `staged_plugins`. The installed file is left untouched. The
ordinary later owned-session staging/snapshot/restoration mechanism applies the
copy; setup itself writes nothing to overwrite or mods.

`provider.capability_manifest` is another external pin object. Its JSON is an
offline build declaration for the exact provider DLL, for example:

```json
{
  "schemaVersion": 1,
  "game_edition": "se",
  "providerSha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "capabilities": ["native-menu-flags", "devbench-startup-ui/1"]
}
```

Replace the illustrative zero hash with the actual 64-character DLL hash.
Doctor always requires `native-menu-flags`. The explicit SE-only
`configuration.se_new_game_ui:true` additionally requires `devbench-startup-ui/1`
from [the native startup recipe](devbench-native-startup.md). Stock version text
alone does not establish either capability. A matching declaration is evidence
of your selected build, not a live capability measurement. The executor must
still read the native contract, actual `alwaysActive` setting, startup/world
readiness and subject outcomes in a separately admitted game session.

Optional staged plugin destinations must appear exactly in
`destination_allowlist`, remain below `SKSE/Plugins/`, and be unique. Source
hashes are checked again by doctor and the executor. A declaration schedules
ordinary reversible staging in a future owned run; setup does not copy these
artifacts into a live installation. To use an acquired replacement DevBench DLL,
declare its own exact staged destination as well as the provider configuration.

## Transaction, provenance and repeat runs

The new directory contains `config.json`, `prepared-devbench-config.json`,
`dependencies-report.json`, `setup-manifest.json` and optionally
`command-bus.json` and `command-channel.json`. Setup validates the generated runner configuration using the
public loader, stages all bytes in a private sibling directory, and publishes
that directory in one rename. Write/validation failure removes only its own
staging files. A foreign lock or existing unrelated configuration is preserved.
Runtime directories and game/MO2 files are not created or changed.

The manifest records release version, setup/configuration source hashes,
specification path/hash, provider/dependency provenance and each generated output
hash. An identical setup rerun verifies all actual output files and reassesses
current dependencies. Changed inputs/source, altered or unexpected outputs,
missing manifest/files and changed provider-source bytes are refused. Select a
new output directory for a revised specification; no overwrite switch exists.
The input specification stays external and unchanged because its exact bytes
are part of the identity. Setup never writes secret token contents to its JSON
responses or manifest, and token files are only checked for existence/nonzero
size; token files cannot serve as artifact sources.

An absent Bridge token can be `deferred-to-owned-mo2-start` for a cold-owned
configuration when the exact pinned Bridge file verifies under the declared
MO2 plugins directory. Some Bridge lifecycles remove the token on manager exit;
the later owned startup must regenerate it and establish the exact live endpoint
identity. Reuse/borrowed-manager mode still requires an existing nonempty token,
and an absent/changed Bridge pin cannot justify deferral. Setup preserves the
declared path and never synthesizes a Bridge credential.

## Optional voice or another command adapter

`command_bus` accepts `http://127.0.0.1:<explicit port>/v1` and an external private
token-file path. This matches the neutral receiver's literal loopback boundary.
The generated `command-bus.json` references these paths and the runner
configuration for an external adapter. `command-channel.json` is immediately
usable by the channel CLI: it selects `runtime/command-channel/commands.sqlite3`,
the declared token path/port, host `127.0.0.1`, 65536 request bytes and a
300-second claim timeout. Setup validates this file but creates no database,
token or runtime directory. Initialize and start the independent receiver
explicitly when authorized:

```powershell
python C:/Tools/skyrim-autotest/run.py --config C:/TestBench/se/config-040/command-channel.json channel init
python C:/Tools/skyrim-autotest/run.py --config C:/TestBench/se/config-040/command-channel.json channel serve
```

Connect a separately installed voice/command adapter through the
[channel API and authentication contract](command-channel.md). No microphone,
listener, ASR executable/model, voice inbox, AI-client hooks or per-utterance chat
relay is installed or started. A missing optional API token is reported without
blocking the automatic executor's offline preparation. API health and deliveries
are not tested by setup/doctor.

Both commands print JSON and exit `0` for offline preparation readiness, `2` for
missing requirements or a refusal. `liveQualified` is always `false`. No offline
result authorizes a game run, supplies a personal fixture, qualifies native
startup, or establishes that a mod passed its functional tests.
