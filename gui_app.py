import asyncio
import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from pathlib import Path
from typing import Optional

from interact_with_obs import OBSGroupTogglerApp
from stream_points import PointLedger, StreamPointsTracker, TrackerCallbacks, TrackerConfig, ViewerPoints


class TrackerGui:
    def __init__(self, parent: tk.Misc, root: tk.Tk) -> None:
        self.parent = parent
        self.root = root
        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.worker_loop: Optional[asyncio.AbstractEventLoop] = None
        self.worker_tracker: Optional[StreamPointsTracker] = None
        self.worker_running = False
        self.obs_app: Optional[OBSGroupTogglerApp] = None
        self.request_output_queue: queue.Queue[str] = queue.Queue()
        self.request_typing_in_progress = False
        self.request_cursor_visible = False

        self.requests_window = self.build_requests_window()
        self.requests_text = self.build_requests_text()
        self.commands_window = self.build_commands_window()
        self.commands_text = self.build_commands_text()

        self.username_var = tk.StringVar()
        self.points_file_var = tk.StringVar(value="stream_points.json")
        self.view_points_var = tk.StringVar(value="10")
        self.view_interval_var = tk.StringVar(value="60")
        self.active_window_var = tk.StringVar(value="180")
        self.like_multiplier_var = tk.StringVar(value="1")
        self.gift_multiplier_var = tk.StringVar(value="1")
        self.save_every_var = tk.StringVar(value="15")
        self.status_var = tk.StringVar(value="Idle")

        self.build_ui()
        self.populate_commands_text()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self.process_events)
        self.root.after(500, self.blink_request_cursor)

    def build_requests_window(self) -> tk.Toplevel:
        window = tk.Toplevel(self.root)
        window.title("Stream Requests")
        window.geometry("720x240")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        window.protocol("WM_DELETE_WINDOW", self.hide_requests_window)
        return window

    def build_requests_text(self) -> tk.Text:
        text = tk.Text(
            self.requests_window,
            wrap="word",
            state="disabled",
            font=("Lucida Console", 14),
            bg="black",
            fg="#00FF66",
            insertbackground="#00FF66",
            relief="flat",
            padx=10,
            pady=10,
        )
        text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self.requests_window, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        return text

    def build_commands_window(self) -> tk.Toplevel:
        window = tk.Toplevel(self.root)
        window.title("Stream Commands")
        window.geometry("720x250")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        window.protocol("WM_DELETE_WINDOW", self.hide_commands_window)
        return window

    def build_commands_text(self) -> tk.Text:
        text = tk.Text(
            self.commands_window,
            wrap="word",
            state="disabled",
            font=("Lucida Console", 14),
            bg="white",
            fg="black",
        )
        text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self.commands_window, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        return text

    def build_ui(self) -> None:
        self.parent.columnconfigure(0, weight=1)
        self.parent.rowconfigure(2, weight=1)
        self.parent.rowconfigure(3, weight=2)

        controls = ttk.LabelFrame(self.parent, text="Tracker Settings", padding=12)
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

        ttk.Label(controls, text="Like Multiplier").grid(
            row=2, column=2, sticky="w", padx=4, pady=4
        )
        ttk.Entry(controls, textvariable=self.like_multiplier_var).grid(
            row=2, column=3, sticky="ew", padx=4, pady=4
        )

        ttk.Label(controls, text="Gift Multiplier").grid(
            row=3, column=0, sticky="w", padx=4, pady=4
        )
        ttk.Entry(controls, textvariable=self.gift_multiplier_var).grid(
            row=3, column=1, sticky="ew", padx=4, pady=4
        )

        ttk.Label(controls, text="Save Every").grid(row=3, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.save_every_var).grid(
            row=3, column=3, sticky="ew", padx=4, pady=4
        )

        actions = ttk.Frame(self.parent, padding=(12, 0, 12, 12))
        actions.grid(row=1, column=0, sticky="ew")
        actions.columnconfigure(3, weight=1)

        self.start_button = ttk.Button(actions, text="Start Tracking", command=self.start_tracking)
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.stop_button = ttk.Button(
            actions, text="Stop Tracking", command=self.stop_tracking, state="disabled"
        )
        self.stop_button.grid(row=0, column=1, padx=(0, 8))

        ttk.Button(actions, text="Clear Log", command=self.clear_log).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(actions, text="Reset Points File", command=self.reset_points_file).grid(
            row=0, column=3, padx=(0, 8)
        )
        ttk.Button(actions, text="Edit Selected Points", command=self.edit_selected_points).grid(
            row=0, column=4, padx=(0, 8)
        )

        ttk.Label(actions, text="Status:").grid(row=0, column=5, sticky="e", padx=(0, 4))
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=6, sticky="w")

        leaderboard_frame = ttk.LabelFrame(self.parent, text="Leaderboard", padding=12)
        leaderboard_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        leaderboard_frame.columnconfigure(0, weight=1)
        leaderboard_frame.rowconfigure(0, weight=1)

        columns = ("user", "total", "watch", "likes", "gift", "diamonds")
        self.tree = ttk.Treeview(leaderboard_frame, columns=columns, show="headings", height=10)
        self.tree.grid(row=0, column=0, sticky="nsew")

        headings = {
            "user": "User",
            "total": "Total Points",
            "watch": "Watch Points",
            "likes": "Like Points",
            "gift": "Gift Points",
            "diamonds": "Gift Diamonds",
        }
        widths = {
            "user": 220,
            "total": 110,
            "watch": 110,
            "likes": 110,
            "gift": 110,
            "diamonds": 110,
        }

        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="center")

        tree_scroll = ttk.Scrollbar(leaderboard_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)

        log_frame = ttk.LabelFrame(self.parent, text="Live Log", padding=12)
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

    def append_request(self, message: str) -> None:
        if not self.requests_window.winfo_viewable():
            self.requests_window.deiconify()
        self.request_output_queue.put(message)
        if not self.request_typing_in_progress:
            self.type_next_request()

    def type_next_request(self) -> None:
        if self.request_output_queue.empty():
            self.request_typing_in_progress = False
            self.set_request_cursor(True)
            return

        self.request_typing_in_progress = True
        self.set_request_cursor(False)
        message = self.request_output_queue.get()
        full_line = f"> {message}\n"
        self.type_request_chars(full_line, 0)

    def type_request_chars(self, text: str, index: int) -> None:
        if index >= len(text):
            self.request_typing_in_progress = False
            self.set_request_cursor(True)
            self.root.after(180, self.type_next_request)
            return

        self.set_request_cursor(False)
        self.requests_text.configure(state="normal")
        self.requests_text.insert("end", text[index])
        self.requests_text.see("end")
        self.requests_text.configure(state="disabled")
        self.root.after(100, lambda: self.type_request_chars(text, index + 1))

    def set_request_cursor(self, visible: bool) -> None:
        if not self.requests_text.winfo_exists():
            return

        if visible == self.request_cursor_visible:
            return

        self.requests_text.configure(state="normal")
        if visible:
            self.requests_text.insert("end", "_")
            self.requests_text.see("end")
        else:
            self.requests_text.delete("end-2c", "end-1c")
        self.requests_text.configure(state="disabled")
        self.request_cursor_visible = visible

    def blink_request_cursor(self) -> None:
        if self.requests_text.winfo_exists():
            if self.request_typing_in_progress:
                self.set_request_cursor(False)
            else:
                self.set_request_cursor(not self.request_cursor_visible)
            self.root.after(500, self.blink_request_cursor)

    def hide_requests_window(self) -> None:
        self.requests_window.withdraw()

    def populate_commands_text(self) -> None:
        lines = [
            "How to gain points:",
            "- Stay active in the stream to",
            "earn watch points over time.",
            "- Send gifts to earn gift points.",
            "",
            "Available commands:",
            "!showpoints",
            "See your current points total.",
            "",
            "!closewindow - 10 points",
            "Redeem to close one window.",
            "",
            "!closeallwindows - 50 points",
            "Redeem to close all windows.",
        ]
        self.commands_text.configure(state="normal")
        self.commands_text.delete("1.0", "end")
        self.commands_text.insert("1.0", "\n".join(lines))
        self.commands_text.configure(state="disabled")

    def hide_commands_window(self) -> None:
        self.commands_window.withdraw()

    def reset_points_file(self) -> None:
        points_file = self.points_file_var.get().strip() or "stream_points.json"

        if self.worker_running:
            messagebox.showwarning(
                "Tracker Running",
                "Stop tracking before resetting the points file.",
                parent=self.root,
            )
            return

        confirmed = messagebox.askyesno(
            "Reset Points File",
            f"Reset all saved viewer points in:\n\n{points_file}\n\nThis cannot be undone.",
            parent=self.root,
        )
        if not confirmed:
            return

        try:
            path = Path(points_file)
            payload = {
                "saved_at": "",
                "viewers": {},
            }
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.tree.delete(*self.tree.get_children())
            self.status_var.set("Points file reset")
            self.append_log(f"Reset points file: {path}")
        except Exception as error:
            messagebox.showerror("Reset Failed", str(error), parent=self.root)

    def edit_selected_points(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning(
                "No User Selected",
                "Select a user in the points list first.",
                parent=self.root,
            )
            return

        item = self.tree.item(selection[0])
        values = item.get("values", [])
        if len(values) < 2:
            return

        user_label = str(values[0])
        current_points = int(values[1])
        unique_id = user_label.lstrip("@")

        new_total = simpledialog.askinteger(
            "Edit Points",
            f"Set total points for {user_label}:",
            parent=self.root,
            initialvalue=current_points,
            minvalue=0,
        )
        if new_total is None:
            return

        try:
            if self.worker_running and self.worker_tracker is not None:
                viewer = self.worker_tracker.ledger.adjust_viewer_points(unique_id, new_total)
                self.worker_tracker.save_ledger()
                self.update_scoreboard(self.worker_tracker.ledger.top_viewers(10))
            else:
                points_file = self.points_file_var.get().strip() or "stream_points.json"
                ledger = PointLedger(points_file)
                viewer = ledger.adjust_viewer_points(unique_id, new_total)
                ledger.save()
                self.update_scoreboard(ledger.top_viewers(10))

            self.status_var.set(f"Updated points for @{viewer.unique_id}")
            self.append_log(f"Adjusted @{viewer.unique_id} to {viewer.total_points} total points")
        except KeyError:
            messagebox.showerror(
                "User Not Found",
                f"{user_label} was not found in the points data.",
                parent=self.root,
            )
        except Exception as error:
            messagebox.showerror("Edit Failed", str(error), parent=self.root)

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
            like_multiplier=self.parse_positive_int(
                self.like_multiplier_var.get(), "Like Multiplier"
            ),
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
            on_request=lambda message: self.event_queue.put(("request", message)),
            on_command=lambda payload: self.event_queue.put(("command", payload)),
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
                iid=viewer.unique_id,
                values=(
                    f"@{viewer.unique_id}",
                    viewer.total_points,
                    viewer.watch_points,
                    viewer.like_points,
                    viewer.gift_points,
                    viewer.gift_diamonds,
                ),
            )

    def handle_command_request(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return

        if self.worker_tracker is None:
            return

        command = str(payload.get("command", ""))
        unique_id = str(payload.get("unique_id", ""))
        cost = int(payload.get("cost", 0))

        viewer = self.worker_tracker.ledger.viewers.get(unique_id)
        if viewer is None:
            self.append_request(f"@{unique_id}: user not found")
            return

        if viewer.total_points < cost:
            self.append_request(
                f"@{viewer.unique_id}: not enough points for {command} ({viewer.total_points}/{cost})"
            )
            return

        if self.obs_app is None or self.obs_app.client is None:
            self.append_request(f"@{viewer.unique_id}: OBS is not connected for {command}")
            return

        try:
            if command == "!closewindow":
                success, obs_message = self.obs_app.hide_random_reward_action()
            elif command == "!closeallwindows":
                success, obs_message, _ = self.obs_app.hide_all_reward_action()
            else:
                return
        except Exception as error:
            self.append_request(f"@{viewer.unique_id}: {command} failed ({error})")
            return

        if not success:
            self.append_request(f"@{viewer.unique_id}: {command} failed ({obs_message})")
            return

        updated_viewer = self.worker_tracker.ledger.adjust_viewer_points(
            viewer.unique_id,
            viewer.total_points - cost,
        )
        self.worker_tracker.save_ledger()
        self.update_scoreboard(self.worker_tracker.ledger.top_viewers(self.worker_tracker.config.top_n))
        self.append_request(
            f"@{updated_viewer.unique_id}: redeemed {command} for {cost} points"
        )
        self.append_log(
            f"Redeemed {command} for @{updated_viewer.unique_id} | cost={cost} | remaining={updated_viewer.total_points}"
        )

    def process_events(self) -> None:
        try:
            while True:
                event_type, payload = self.event_queue.get_nowait()

                if event_type == "log":
                    self.append_log(str(payload))
                elif event_type == "request":
                    self.append_request(str(payload))
                elif event_type == "command":
                    self.handle_command_request(payload)
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
        if self.requests_window.winfo_exists():
            self.requests_window.destroy()
        if self.commands_window.winfo_exists():
            self.commands_window.destroy()
        self.root.destroy()


def launch_gui() -> None:
    root = tk.Tk()
    root.title("TikTok Stream Tools")
    root.geometry("1024x760")
    ttk.Style().theme_use("clam")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    notebook = ttk.Notebook(root)
    notebook.grid(row=0, column=0, sticky="nsew")

    obs_tab = ttk.Frame(notebook)
    points_tab = ttk.Frame(notebook)

    notebook.add(obs_tab, text="OBS Controls")
    notebook.add(points_tab, text="Stream Points")

    obs_app = OBSGroupTogglerApp(obs_tab)
    tracker_gui = TrackerGui(points_tab, root)
    tracker_gui.obs_app = obs_app
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
