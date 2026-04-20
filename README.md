# TikTok Stream Viewer Tracker

This script connects to a TikTok LIVE and tracks:

- live viewer-count updates
- users who trigger visible join events

Important limitation: TikTok does not expose a reliable full list of everyone currently watching through the unofficial LIVE event stream. In practice, this means the script can show:

- the current viewer count
- users who announce themselves by triggering a join event

It cannot guarantee a complete list of every silent viewer currently in the room.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Main Launcher

Run the app from one entry point:

```powershell
python .\main.py
```

That opens the desktop GUI by default.

If you want the terminal version instead:

```powershell
python .\main.py cli your_tiktok_username
```

## Usage

```powershell
python .\watch_stream_viewers.py your_tiktok_username
```

You can also print the running set of seen users:

```powershell
python .\watch_stream_viewers.py your_tiktok_username --show-seen
```

## Points Tracker

`stream_points.py` is a separate module for a simple loyalty system. It:

- tracks viewers who surface through join or other visible activity
- awards watch-time points at a fixed interval while a viewer remains recently active
- awards gift points based on the gift's diamond value
- saves the running scoreboard to `stream_points.json`

Important limitation: TikTok does not expose a reliable full "currently watching" roster or a dependable leave event here, so watch-time is an approximation based on recent visible activity.

### Usage

```powershell
python .\stream_points.py your_tiktok_username
```

### Example tuning

```powershell
python .\stream_points.py your_tiktok_username --view-points 5 --view-interval 60 --active-window 180 --gift-multiplier 2
```

## GUI

`main.py` launches a Tkinter GUI with:

- start and stop controls
- editable tracker settings
- live log output
- a leaderboard showing total, watch, and gift points

The GUI and CLI both use the same tracking logic in `stream_points.py`, so they stay in sync behavior-wise.
