import asyncio
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from stream_points import StreamPointsTracker, TrackerCallbacks, TrackerConfig, ViewerPoints


class TrackerGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("TikTok Stream Points Tracker")
        self.root.geometry("980x700")

        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.worker_loop: Optional[asyncio.AbstractEventLoop] = None
        self.worker_tracker: Optional[StreamPointsTracker] = None
        self.worker_running = False

        self.username_var = tk.StringVar()
        self.points_file_var = tk.StringVar(value="stream_points.json")
        self.view_points_var = tk.StringVar(value="10")
        self.view_interval_var = tk.StringVar(value="60")
        self.active_window_var = tk.StringVar(value="180")
        self.gift_multiplier_var = tk.StringVar(value="1")
        self.save_every_var = tk.StringVar(value="15")
        self.status_var = tk.StringVar(value="Idle")

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self.process_events)

    def build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        self.root.rowconfigure(3, weight=2)

        controls = ttk.LabelFrame(self.root, text="Tracker Settings", padding=12)
        controls.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="Username").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.username_var).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )

        ttk.Label(controls, text="Points File").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.points_file_var).grid(
            row=0, column=3, sticky="ew", padx=4, pady=4
        )

        ttk.Label(controls, text="View Points").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.view_points_var).grid(
            row=1, column=1, sticky="ew", padx=4, pady=4
        )

        ttk.Label(controls, text="View Interval").grid(row=1, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.view_interval_var).grid(
            row=1, column=3, sticky="ew", padx=4, pady=4
        )

        ttk.Label(controls, text="Active Window").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.active_window_var).grid(
            row=2, column=1, sticky="ew", padx=4, pady=4
        )

        ttk.Label(controls, text="Gift Multiplier").grid(
            row=2, column=2, sticky="w", padx=4, pady=4
        )
        ttk.Entry(controls, textvariable=self.gift_multiplier_var).grid(
            row=2, column=3, sticky="ew", padx=4, pady=4
        )

        ttk.Label(controls, text="Save Every").grid(row=3, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.save_every_var).grid(
            row=3, column=1, sticky="ew", padx=4, pady=4
        )

        actions = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        actions.grid(row=1, column=0, sticky="ew")
        actions.columnconfigure(3, weight=1)

        self.start_button = ttk.Button(actions, text="Start Tracking", command=self.start_tracking)
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.stop_button = ttk.Button(
            actions, text="Stop Tracking", command=self.stop_tracking, state="disabled"
        )
        self.stop_button.grid(row=0, column=1, padx=(0, 8))

        ttk.Button(actions, text="Clear Log", command=self.clear_log).grid(row=0, column=2, padx=(0, 8))

        ttk.Label(actions, text="Status:").grid(row=0, column=3, sticky="e", padx=(0, 4))
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=4, sticky="w")

        leaderboard_frame = ttk.LabelFrame(self.root, text="Leaderboard", padding=12)
        leaderboard_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        leaderboard_frame.columnconfigure(0, weight=1)
        leaderboard_frame.rowconfigure(0, weight=1)

        columns = ("user", "total", "watch", "gift", "diamonds")
        self.tree = ttk.Treeview(leaderboard_frame, columns=columns, show="headings", height=10)
        self.tree.grid(row=0, column=0, sticky="nsew")

        headings = {
            "user": "User",
            "total": "Total Points",
            "watch": "Watch Points",
            "gift": "Gift Points",
            "diamonds": "Gift Diamonds",
        }
        widths = {"user": 220, "total": 110, "watch": 110, "gift": 110, "diamonds": 110}

        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="center")

        tree_scroll = ttk.Scrollbar(leaderboard_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)

        log_frame = ttk.LabelFrame(self.root, text="Live Log", padding=12)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap="word", state="disabled", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def parse_positive_int(self, raw_value: str, field_name: str) -> int:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a whole number.") from exc

        if value <= 0:
            raise ValueError(f"{field_name} must be greater than 0.")

        return value

    def build_config(self) -> TrackerConfig:
        username = self.username_var.get().strip()
        if not username:
            raise ValueError("Username is required.")

        return TrackerConfig(
            username=username,
            points_file=self.points_file_var.get().strip() or "stream_points.json",
            view_points=self.parse_positive_int(self.view_points_var.get(), "View Points"),
            view_interval=self.parse_positive_int(self.view_interval_var.get(), "View Interval"),
            active_window=self.parse_positive_int(self.active_window_var.get(), "Active Window"),
            gift_multiplier=self.parse_positive_int(
                self.gift_multiplier_var.get(), "Gift Multiplier"
            ),
            save_every=self.parse_positive_int(self.save_every_var.get(), "Save Every"),
        )

    def set_running_state(self, running: bool) -> None:
        self.worker_running = running
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def start_tracking(self) -> None:
        if self.worker_running:
            return

        try:
            config = self.build_config()
        except ValueError as error:
            messagebox.showerror("Invalid Settings", str(error), parent=self.root)
            return

        callbacks = TrackerCallbacks(
            on_log=lambda message: self.event_queue.put(("log", message)),
            on_status=lambda status: self.event_queue.put(("status", status)),
            on_scoreboard=lambda viewers: self.event_queue.put(("scoreboard", viewers)),
        )

        self.set_running_state(True)
        self.status_var.set("Starting")
        self.append_log(f"Starting tracker for @{config.normalized_username}")

        def worker() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.worker_loop = loop
            self.worker_tracker = StreamPointsTracker(config, callbacks)

            try:
                loop.run_until_complete(self.worker_tracker.start())
            except Exception as exc:
                self.event_queue.put(("error", str(exc)))
            finally:
                self.event_queue.put(("stopped", None))
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                finally:
                    loop.close()

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def stop_tracking(self) -> None:
        if not self.worker_running or self.worker_loop is None or self.worker_tracker is None:
            return

        future = asyncio.run_coroutine_threadsafe(self.worker_tracker.stop(), self.worker_loop)

        def done_callback(_: object) -> None:
            return

        future.add_done_callback(done_callback)

    def update_scoreboard(self, viewers: list[ViewerPoints]) -> None:
        self.tree.delete(*self.tree.get_children())
        for viewer in viewers:
            self.tree.insert(
                "",
                "end",
                values=(
                    f"@{viewer.unique_id}",
                    viewer.total_points,
                    viewer.watch_points,
                    viewer.gift_points,
                    viewer.gift_diamonds,
                ),
            )

    def process_events(self) -> None:
        try:
            while True:
                event_type, payload = self.event_queue.get_nowait()

                if event_type == "log":
                    self.append_log(str(payload))
                elif event_type == "status":
                    self.status_var.set(str(payload))
                elif event_type == "scoreboard":
                    self.update_scoreboard(payload)  # type: ignore[arg-type]
                elif event_type == "error":
                    self.append_log(f"Error: {payload}")
                    messagebox.showerror("Tracker Error", str(payload), parent=self.root)
                elif event_type == "stopped":
                    self.set_running_state(False)
                    self.status_var.set("Stopped")
                    self.worker_loop = None
                    self.worker_tracker = None
                    self.worker_thread = None
        except queue.Empty:
            pass
        finally:
            self.root.after(200, self.process_events)

    def on_close(self) -> None:
        if self.worker_running:
            self.stop_tracking()
            self.root.after(250, self.finish_close)
            return

        self.root.destroy()

    def finish_close(self) -> None:
        if self.worker_running:
            self.root.after(250, self.finish_close)
            return
        self.root.destroy()


def launch_gui() -> None:
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    TrackerGui(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
