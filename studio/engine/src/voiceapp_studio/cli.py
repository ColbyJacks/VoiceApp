"""Command line for Studio until its own UI exists (and for scripting after)."""

from __future__ import annotations

import argparse
import sys

from voiceapp_studio.project import STEPS, Project, TrainingConfig


def _cmd_new(args: argparse.Namespace) -> int:
    config = TrainingConfig(
        name=args.name, sample_rate=args.sample_rate, version=args.version, epochs=args.epochs
    )
    project = Project.create(args.path, config)
    print(f"Created {project.root}. Put your recordings in {project.root / 'dataset'}.")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    from voiceapp_core import load_model_info

    info = load_model_info(args.model)
    print(f"{info.name}: {info.version}, {info.sample_rate} Hz, pitch {'on' if info.uses_pitch else 'off'}")
    return 0


def _cmd_step(args: argparse.Namespace) -> int:
    Project(args.path).load_config()
    print(f"'{args.command}' is not implemented yet.", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voiceapp-studio", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="create a training project folder")
    new.add_argument("path")
    new.add_argument("--name", required=True)
    new.add_argument("--sample-rate", type=int, default=40000)
    new.add_argument("--version", default="v2", choices=["v1", "v2"])
    new.add_argument("--epochs", type=int, default=200)
    new.set_defaults(func=_cmd_new)

    inspect = sub.add_parser("inspect", help="show details of a .pth voice model")
    inspect.add_argument("model")
    inspect.set_defaults(func=_cmd_inspect)

    for step in STEPS:
        p = sub.add_parser(step, help=f"run the {step} step on a project")
        p.add_argument("path")
        p.set_defaults(func=_cmd_step)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
