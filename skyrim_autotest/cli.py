"""Single public entrypoint; stdlib-only and independent of project infrastructure."""
import argparse
import json
import os
from pathlib import Path
import sys
from . import __version__
from .config import P, ConfigurationError, load, template

def main(argv=None):
    parser = argparse.ArgumentParser(prog="skyrim-autotest")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, help="External configuration JSON; required for live operations")
    parser.add_argument("command", choices=["init", "config-check", "preflight", "run", "status", "recover", "queue", "build-driver", "guardian", "guide", "review-plan", "validate-native14"])
    args, rest = parser.parse_known_args(argv)
    try:
        if args.command == 'validate-native14':
            from .native14_cli import main as validate_native14
            return validate_native14(rest)
        if args.command == 'review-plan':
            from .test_plan import main as review
            return review(rest)
        if args.command == "guide":
            from importlib.resources import files
            print(files("skyrim_autotest").joinpath("AI_AGENTS.md").read_text(encoding="utf-8"))
            return 0
        if args.command == "init":
            sub = argparse.ArgumentParser(prog="skyrim-autotest init")
            sub.add_argument("--directory", type=Path, required=True)
            sub.add_argument("--edition", choices=['vr', 'se'], default='vr')
            options = sub.parse_args(rest)
            directory = options.directory.resolve()
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "config.json").open("x", encoding="utf-8") as stream:
                json.dump(template(options.edition), stream, indent=2)
            from importlib.resources import files
            examples = files("skyrim_autotest").joinpath("examples")
            for file in examples.iterdir():
                if file.name.endswith(".json"):
                    if options.edition == 'se':
                        continue
                    with (directory / file.name).open("x", encoding="utf-8") as stream:
                        stream.write(file.read_text(encoding="utf-8"))
            if options.edition == 'se':
                with (directory / 'se-world-smoke.json').open('x', encoding='utf-8') as stream:
                    json.dump({'schemaVersion': 1, 'cell': 'QASmoke', 'steps': [
                        {'name': 'world loaded (tool selftest only)', 'tool': 'inspect',
                         'args': {'kind': 'scene'}, 'assert': [
                             {'path': 'playerLoaded', 'equals': True},
                             {'path': 'cell.editorId', 'equals': 'QASmoke'}]}]}, stream, indent=2)
            print(json.dumps({"configuration": str(directory / "config.json"), "instruction": "Replace paths and supply hash-pinned authorized fixture before running"}))
            return 0
        from . import runner, native
        if args.command == "guardian":
            if len(rest) != 1:
                raise ConfigurationError("Guardian needs exactly one run directory")
            directory = Path(rest[0]).resolve()
            state = runner.read_json(directory / "state.json")
            runner.configure(state["configuration"])
            runner.guardian(directory)
            return 0
        if not args.config:
            raise ConfigurationError("Use --config <external JSON> for " + args.command)
        value = load(args.config)
        runner.configure(value)
        if args.command == "config-check":
            if rest:
                raise ConfigurationError("Unexpected arguments to config-check")
            # Tokens are paths only; their contents are never read or returned here.
            print(json.dumps({"schemaVersion": 1, "configurationValid": True, "runtime": str(P.runtime), "windows": os.name == "nt"}, indent=2))
            return 0
        if args.command == "status":
            return runner.main(["status", *rest])
        if os.name != "nt":
            raise ConfigurationError("Live testing and recovery require Windows")
        if args.command == "build-driver":
            if value.get('game_edition') == 'se':
                raise ConfigurationError('Skyrim SE does not use the VR driver')
            if rest:
                raise ConfigurationError("Unexpected arguments to build-driver")
            from .build_driver import main as build
            build()
            return 0
        if args.command == "queue":
            from .queue import main as queue
            return queue(rest)
        return runner.main([args.command, *rest])
    except (ConfigurationError, runner.Blocked if "runner" in locals() else ConfigurationError, native.Busy if "native" in locals() else ConfigurationError, OSError, ValueError) as error:
        print(json.dumps({"result": "blocked", "reason": str(error)}))
        return 2
