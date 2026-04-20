import argparse
import asyncio
import json
import signal
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from TikTokLive import TikTokLiveClient
    from TikTokLive.events import (
        CommentEvent,
        ConnectEvent,
        DisconnectEvent,
        FollowEvent,
        GiftEvent,
        JoinEvent,
        LikeEvent,
        ShareEvent,
    )
    TIKTOKLIVE_IMPORT_ERROR: Optional[ModuleNotFoundError] = None
except ModuleNotFoundError as exc:
    TikTokLiveClient = None  # type: ignore[assignment]
    CommentEvent = ConnectEvent = DisconnectEvent = FollowEvent = GiftEvent = object  # type: ignore[assignment]
    JoinEvent = LikeEvent = ShareEvent = object  # type: ignore[assignment]
    TIKTOKLIVE_IMPORT_ERROR = exc


LogCallback = Callable[[str], None]
StatusCallback = Callable[[str], None]
ScoreboardCallback = Callable[[list["ViewerPoints"]], None]


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def utc_now() -> datetime:
    return datetime.utcnow()


@dataclass
class ViewerPoints:
    unique_id: str
    nickname: str
    total_points: int = 0
    watch_points: int = 0
    gift_points: int = 0
    watch_intervals: int = 0
    gift_count: int = 0
    gift_diamonds: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    last_point_award_at: str = ""


@dataclass
class TrackerConfig:
    username: str
    points_file: str = "stream_points.json"
    view_points: int = 10
    view_interval: int = 60
    active_window: int = 180
    gift_multiplier: int = 1
    save_every: int = 15
    top_n: int = 10

    @property
    def normalized_username(self) -> str:
        return self.username.lstrip("@")

    @property
    def unique_id(self) -> str:
        return f"@{self.normalized_username}"


@dataclass
class TrackerCallbacks:
    on_log: Optional[LogCallback] = None
    on_status: Optional[StatusCallback] = None
    on_scoreboard: Optional[ScoreboardCallback] = None


class PointLedger:
    def __init__(self, file_path: str) -> None:
        self.file_path = Path(file_path)
        self.viewers: dict[str, ViewerPoints] = {}
        self.load()

    def load(self) -> None:
        if not self.file_path.exists():
            return

        raw_data = json.loads(self.file_path.read_text(encoding="utf-8"))
        viewers = raw_data.get("viewers", {})
        for unique_id, payload in viewers.items():
            self.viewers[unique_id] = ViewerPoints(**payload)

    def save(self) -> None:
        payload = {
            "saved_at": utc_now().isoformat(),
            "viewers": {
                unique_id: asdict(viewer)
                for unique_id, viewer in sorted(self.viewers.items())
            },
        }
        self.file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def top_viewers(self, limit: int = 10) -> list[ViewerPoints]:
        return sorted(
            self.viewers.values(),
            key=lambda viewer: viewer.total_points,
            reverse=True,
        )[:limit]

    def ensure_viewer(
        self,
        unique_id: str,
        nickname: str,
        seen_at: datetime,
    ) -> ViewerPoints:
        viewer = self.viewers.get(unique_id)
        seen_at_str = seen_at.isoformat()

        if viewer is None:
            viewer = ViewerPoints(
                unique_id=unique_id,
                nickname=nickname,
                first_seen_at=seen_at_str,
                last_seen_at=seen_at_str,
                last_point_award_at=seen_at_str,
            )
            self.viewers[unique_id] = viewer
            return viewer

        viewer.nickname = nickname
        viewer.last_seen_at = seen_at_str
        if not viewer.first_seen_at:
            viewer.first_seen_at = seen_at_str
        if not viewer.last_point_award_at:
            viewer.last_point_award_at = seen_at_str
        return viewer

    def mark_active(self, unique_id: str, nickname: str, seen_at: datetime) -> ViewerPoints:
        viewer = self.ensure_viewer(unique_id, nickname, seen_at)
        viewer.last_seen_at = seen_at.isoformat()
        return viewer

    def award_watch_points(
        self,
        now: datetime,
        view_interval: int,
        active_window: int,
        points_per_interval: int,
    ) -> list[tuple[ViewerPoints, int]]:
        updates: list[tuple[ViewerPoints, int]] = []

        for viewer in self.viewers.values():
            if not viewer.last_seen_at or not viewer.last_point_award_at:
                continue

            last_seen_at = datetime.fromisoformat(viewer.last_seen_at)
            last_award_at = datetime.fromisoformat(viewer.last_point_award_at)

            if (now - last_seen_at).total_seconds() > active_window:
                continue

            completed_intervals = int((now - last_award_at).total_seconds() // view_interval)
            if completed_intervals <= 0:
                continue

            awarded_points = completed_intervals * points_per_interval
            viewer.watch_intervals += completed_intervals
            viewer.watch_points += awarded_points
            viewer.total_points += awarded_points
            viewer.last_point_award_at = (
                last_award_at + timedelta(seconds=completed_intervals * view_interval)
            ).isoformat()
            updates.append((viewer, awarded_points))

        return updates

    def award_gift_points(
        self,
        unique_id: str,
        nickname: str,
        diamonds: int,
        repeat_count: int,
        gift_multiplier: int,
        seen_at: datetime,
    ) -> ViewerPoints:
        viewer = self.mark_active(unique_id, nickname, seen_at)
        total_diamonds = max(diamonds, 0) * max(repeat_count, 1)
        awarded_points = total_diamonds * gift_multiplier

        viewer.gift_count += max(repeat_count, 1)
        viewer.gift_diamonds += total_diamonds
        viewer.gift_points += awarded_points
        viewer.total_points += awarded_points
        return viewer


@dataclass
class TrackerState:
    connected: bool = False
    room_id: Optional[int] = None
    latest_status: str = "Idle"
    latest_viewer_count: Optional[int] = None
    seen_user_count: int = 0
    tracked_user_count: int = 0
    last_saved_at: str = ""
    seen_users: set[str] = field(default_factory=set)


def get_user_identity(event: Any) -> tuple[Optional[str], Optional[str]]:
    user = getattr(event, "user", None)
    if user is None:
        return None, None

    unique_id = getattr(user, "unique_id", None) or getattr(user, "nickname", None)
    nickname = getattr(user, "nickname", None) or unique_id
    return unique_id, nickname


def get_gift_repeat_count(event: GiftEvent) -> int:
    repeat_count = getattr(event, "repeat_count", None)
    if repeat_count is None:
        return 1
    return max(int(repeat_count), 1)


def get_gift_diamond_count(event: GiftEvent) -> int:
    gift = getattr(event, "gift", None)
    if gift is None:
        return 0

    candidates = [
        getattr(gift, "diamond_count", None),
        getattr(getattr(gift, "info", None), "diamond_count", None),
        getattr(getattr(gift, "extended_gift", None), "diamond_count", None),
        getattr(getattr(gift, "info", None), "price", None),
    ]

    for candidate in candidates:
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)

    return 0


def should_count_gift(event: GiftEvent) -> bool:
    gift = getattr(event, "gift", None)
    if gift is None:
        return False

    streakable = bool(getattr(gift, "streakable", False))
    streaking = bool(getattr(event, "streaking", False))
    return (not streakable) or (streakable and not streaking)


async def autosave_loop(ledger: PointLedger, save_every: int, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=save_every)
        except asyncio.TimeoutError:
            ledger.save()


async def watch_point_loop(
    tracker: "StreamPointsTracker",
    stop_event: asyncio.Event,
) -> None:
    sleep_seconds = max(1, min(tracker.config.view_interval, 5))

    while not stop_event.is_set():
        awarded = tracker.ledger.award_watch_points(
            now=utc_now(),
            view_interval=tracker.config.view_interval,
            active_window=tracker.config.active_window,
            points_per_interval=tracker.config.view_points,
        )

        for viewer, points in awarded:
            tracker.log(
                f"[{timestamp()}] Watch points: @{viewer.unique_id} +{points} "
                f"| total={viewer.total_points} | watch_intervals={viewer.watch_intervals}"
            )

        if awarded:
            tracker.publish_scoreboard()

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=sleep_seconds)
        except asyncio.TimeoutError:
            continue


class StreamPointsTracker:
    def __init__(
        self,
        config: TrackerConfig,
        callbacks: Optional[TrackerCallbacks] = None,
    ) -> None:
        self.config = config
        self.callbacks = callbacks or TrackerCallbacks()
        self.ledger = PointLedger(config.points_file)
        self.client = None
        self.stop_event = asyncio.Event()
        self.state = TrackerState(tracked_user_count=len(self.ledger.viewers))

    def log(self, message: str) -> None:
        if self.callbacks.on_log is not None:
            self.callbacks.on_log(message)
        else:
            print(message)

    def set_status(self, status: str) -> None:
        self.state.latest_status = status
        if self.callbacks.on_status is not None:
            self.callbacks.on_status(status)

    def publish_scoreboard(self) -> None:
        self.state.tracked_user_count = len(self.ledger.viewers)
        if self.callbacks.on_scoreboard is not None:
            self.callbacks.on_scoreboard(self.ledger.top_viewers(self.config.top_n))

    def save_ledger(self) -> None:
        self.ledger.save()
        self.state.last_saved_at = utc_now().isoformat()

    async def start(self) -> None:
        self.ensure_dependency()
        self.client = TikTokLiveClient(unique_id=self.config.unique_id)
        self.register_handlers()
        self.set_status("Connecting")
        loop = asyncio.get_running_loop()

        def request_shutdown() -> None:
            if not self.stop_event.is_set():
                self.log(f"[{timestamp()}] Shutdown requested")
                self.stop_event.set()
                self.set_status("Stopping")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, request_shutdown)
            except NotImplementedError:
                pass

        tasks = [
            asyncio.create_task(self.client.connect()),
            asyncio.create_task(autosave_loop(self.ledger, self.config.save_every, self.stop_event)),
            asyncio.create_task(watch_point_loop(self, self.stop_event)),
            asyncio.create_task(self.stop_event.wait()),
        ]

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        if self.stop_event.is_set():
            self.set_status("Stopping")
            await self.client.disconnect()

        for task in pending:
            task.cancel()

        await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.gather(*done, return_exceptions=True)

        self.save_ledger()
        self.publish_scoreboard()
        self.print_summary()
        self.set_status("Stopped")

    async def stop(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        self.set_status("Stopping")
        if self.client is not None:
            await self.client.disconnect()

    def register_handlers(self) -> None:
        if self.client is None:
            raise RuntimeError("Tracker client is not initialized.")

        @self.client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent) -> None:
            self.state.connected = True
            self.state.room_id = self.client.room_id
            self.set_status("Connected")
            self.log(
                f"[{timestamp()}] Connected to @{event.unique_id} | room_id={self.client.room_id}"
            )

        @self.client.on(DisconnectEvent)
        async def on_disconnect(_: DisconnectEvent) -> None:
            self.state.connected = False
            self.log(f"[{timestamp()}] Disconnected from stream")
            self.set_status("Disconnected")
            self.stop_event.set()

        @self.client.on(JoinEvent)
        async def on_join(event: JoinEvent) -> None:
            unique_id, nickname = get_user_identity(event)
            if unique_id is None or nickname is None:
                return

            is_new_join = unique_id not in self.state.seen_users
            self.state.seen_users.add(unique_id)
            self.state.seen_user_count = len(self.state.seen_users)
            viewer = self.ledger.mark_active(unique_id, nickname, utc_now())
            join_type = "new join" if is_new_join else "repeat join"
            self.log(
                f"[{timestamp()}] {join_type}: @{viewer.unique_id} ({viewer.nickname}) "
                f"| seen_users={self.state.seen_user_count}"
            )
            self.publish_scoreboard()

        @self.client.on(CommentEvent)
        async def on_comment(event: CommentEvent) -> None:
            await self.mark_event_active(event)

        @self.client.on(LikeEvent)
        async def on_like(event: LikeEvent) -> None:
            await self.mark_event_active(event)

        @self.client.on(FollowEvent)
        async def on_follow(event: FollowEvent) -> None:
            await self.mark_event_active(event)

        @self.client.on(ShareEvent)
        async def on_share(event: ShareEvent) -> None:
            await self.mark_event_active(event)

        @self.client.on(GiftEvent)
        async def on_gift(event: GiftEvent) -> None:
            if not should_count_gift(event):
                return

            unique_id, nickname = get_user_identity(event)
            if unique_id is None or nickname is None:
                return

            repeat_count = get_gift_repeat_count(event)
            diamonds = get_gift_diamond_count(event)
            viewer = self.ledger.award_gift_points(
                unique_id=unique_id,
                nickname=nickname,
                diamonds=diamonds,
                repeat_count=repeat_count,
                gift_multiplier=self.config.gift_multiplier,
                seen_at=utc_now(),
            )

            gift_name = getattr(getattr(event, "gift", None), "name", "unknown gift")
            awarded_points = diamonds * repeat_count * self.config.gift_multiplier
            self.log(
                f"[{timestamp()}] Gift tracked: @{viewer.unique_id} sent "
                f"{repeat_count}x {gift_name} | +{awarded_points} points | total={viewer.total_points}"
            )
            self.publish_scoreboard()

    async def mark_event_active(self, event: Any) -> None:
        unique_id, nickname = get_user_identity(event)
        if unique_id is None or nickname is None:
            return

        self.ledger.mark_active(unique_id, nickname, utc_now())

    def print_summary(self) -> None:
        top_viewers = self.ledger.top_viewers(self.config.top_n)
        if top_viewers:
            self.log(f"[{timestamp()}] Top viewers:")
            for viewer in top_viewers:
                self.log(
                    f"  @{viewer.unique_id} | total={viewer.total_points} "
                    f"| watch={viewer.watch_points} | gift={viewer.gift_points}"
                )
        else:
            self.log(f"[{timestamp()}] No viewers were tracked.")

    def ensure_dependency(self) -> None:
        if TIKTOKLIVE_IMPORT_ERROR is not None:
            raise RuntimeError(
                "TikTokLive is not installed. Run 'pip install -r requirements.txt' first."
            ) from TIKTOKLIVE_IMPORT_ERROR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Track TikTok LIVE watch-time and gift points."
    )
    parser.add_argument(
        "username",
        help="TikTok username for the live stream, with or without the leading @",
    )
    parser.add_argument(
        "--points-file",
        default="stream_points.json",
        help="JSON file used to persist the running scoreboard",
    )
    parser.add_argument(
        "--view-points",
        type=int,
        default=10,
        help="Points awarded for each completed view interval",
    )
    parser.add_argument(
        "--view-interval",
        type=int,
        default=60,
        help="Seconds of active viewing needed to award view points",
    )
    parser.add_argument(
        "--active-window",
        type=int,
        default=180,
        help="Seconds a viewer stays eligible after their last visible activity",
    )
    parser.add_argument(
        "--gift-multiplier",
        type=int,
        default=1,
        help="Points awarded per gift diamond",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=15,
        help="Seconds between automatic scoreboard saves",
    )
    return parser.parse_args()


def build_config_from_args(args: argparse.Namespace) -> TrackerConfig:
    return TrackerConfig(
        username=args.username,
        points_file=args.points_file,
        view_points=args.view_points,
        view_interval=args.view_interval,
        active_window=args.active_window,
        gift_multiplier=args.gift_multiplier,
        save_every=args.save_every,
    )


async def main() -> None:
    args = parse_args()
    tracker = StreamPointsTracker(build_config_from_args(args))
    await tracker.start()


if __name__ == "__main__":
    asyncio.run(main())
