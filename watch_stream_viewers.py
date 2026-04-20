import argparse
import asyncio
import signal
from datetime import datetime
from typing import Optional

from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent, JoinEvent, RoomUserSeqEvent


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect to a TikTok LIVE and track join events plus viewer counts."
    )
    parser.add_argument(
        "username",
        help="TikTok username for the live stream, with or without the leading @",
    )
    parser.add_argument(
        "--show-seen",
        action="store_true",
        help="Print the full seen-user list after each new join",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    username = args.username.lstrip("@")
    client = TikTokLiveClient(unique_id=f"@{username}")

    seen_users: set[str] = set()
    latest_viewer_count: Optional[int] = None

    @client.on(ConnectEvent)
    async def on_connect(event: ConnectEvent) -> None:
        print(f"[{timestamp()}] Connected to @{event.unique_id} | room_id={client.room_id}")

    @client.on(RoomUserSeqEvent)
    async def on_room_user_seq(event: RoomUserSeqEvent) -> None:
        nonlocal latest_viewer_count

        viewer_count = getattr(event, "viewer_count", None)
        if viewer_count is None:
            return

        if viewer_count != latest_viewer_count:
            latest_viewer_count = viewer_count
            print(f"[{timestamp()}] Viewer count: {viewer_count}")

    @client.on(JoinEvent)
    async def on_join(event: JoinEvent) -> None:
        user = getattr(event, "user", None)
        if user is None:
            return

        unique_id = getattr(user, "unique_id", None) or getattr(user, "nickname", "unknown")
        nickname = getattr(user, "nickname", unique_id)

        is_new = unique_id not in seen_users
        seen_users.add(unique_id)

        status = "new join" if is_new else "repeat join"
        print(
            f"[{timestamp()}] {status}: @{unique_id} ({nickname}) | "
            f"seen_users={len(seen_users)}"
        )

        if args.show_seen:
            ordered_users = ", ".join(sorted(seen_users))
            print(f"[{timestamp()}] Seen users: {ordered_users}")

    @client.on(DisconnectEvent)
    async def on_disconnect(_: DisconnectEvent) -> None:
        print(f"[{timestamp()}] Disconnected | total_seen_users={len(seen_users)}")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def request_shutdown() -> None:
        if not stop_event.is_set():
            print(f"[{timestamp()}] Shutdown requested")
            stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except NotImplementedError:
            pass

    client_task = asyncio.create_task(client.connect())
    stop_task = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        {client_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_task in done and not client_task.done():
        await client.disconnect()

    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.gather(*done, return_exceptions=True)

    if seen_users:
        ordered_users = ", ".join(sorted(seen_users))
        print(f"[{timestamp()}] Final seen users ({len(seen_users)}): {ordered_users}")
    else:
        print(f"[{timestamp()}] No join events were captured.")


if __name__ == "__main__":
    asyncio.run(main())
