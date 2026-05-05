import argparse
import asyncio

from gui_app import launch_gui
from stream_points import StreamPointsTracker, TrackerConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launcher for the TikTok stream points tracker."
    )
    subparsers = parser.add_subparsers(dest="mode")

    gui_parser = subparsers.add_parser("gui", help="Launch the desktop GUI")
    gui_parser.set_defaults(mode="gui")

    cli_parser = subparsers.add_parser("cli", help="Run the tracker in the terminal")
    cli_parser.add_argument("username", help="TikTok username, with or without @")
    cli_parser.add_argument("--points-file", default="stream_points.json")
    cli_parser.add_argument("--view-points", type=int, default=10)
    cli_parser.add_argument("--view-interval", type=int, default=60)
    cli_parser.add_argument("--active-window", type=int, default=180)
    cli_parser.add_argument("--like-multiplier", type=int, default=1)
    cli_parser.add_argument("--gift-multiplier", type=int, default=1)
    cli_parser.add_argument("--save-every", type=int, default=15)

    return parser


def build_config_from_args(args: argparse.Namespace) -> TrackerConfig:
    return TrackerConfig(
        username=args.username,
        points_file=args.points_file,
        view_points=args.view_points,
        view_interval=args.view_interval,
        active_window=args.active_window,
        like_multiplier=args.like_multiplier,
        gift_multiplier=args.gift_multiplier,
        save_every=args.save_every,
    )


async def run_cli(args: argparse.Namespace) -> None:
    tracker = StreamPointsTracker(build_config_from_args(args))
    await tracker.start()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.mode in (None, "gui"):
        launch_gui()
        return

    asyncio.run(run_cli(args))


if __name__ == "__main__":
    main()
