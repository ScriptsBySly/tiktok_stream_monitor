import asyncio
import ctypes
import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from pathlib import Path
from typing import Optional

from interact_with_obs import OBSGroupTogglerApp, OBSWindowPresetApp
from stream_points import PointLedger, StreamPointsTracker, TrackerCallbacks, TrackerConfig, ViewerPoints


IMAGE_DIR = Path(r"H:\Projects\OBS\Notification")
SOUND_DIR = IMAGE_DIR.parent
NOTIFICATIONS = {
    "Follower": {
        "image": IMAGE_DIR / "Follower.png",
        "sound": SOUND_DIR / "Follower.mp3",
    },
    "Gift": {
        "image": IMAGE_DIR / "Gift.png",
        "sound": SOUND_DIR / "Gift.mp3",
    },
    "Super": {
        "image": IMAGE_DIR / "Super.png",
        "sound": SOUND_DIR / "Super.mp3",
    },
}
MESSAGE_BOX = {
    "start_column": 2,
    "start_row": 6,
    "end_column": 9,
    "end_row": 7,
}
USERNAME_BOX = {
    "start_column": 2,
    "start_row": 4,
    "end_column": 9,
    "end_row": 4,
}
GIFT_BOX = {
    "start_column": 2,
    "start_row": 5,
    "end_column": 9,
    "end_row": 5,
}
USERNAME_COLORS = {
    "Windows XP Blue": "#245edb",
    "Black/Gray": "#3a3a3a",
}
APP_SETTINGS_PATH = Path("stream_tools_settings.json")


def save_app_settings(
    root: tk.Tk,
    obs_app: OBSGroupTogglerApp,
    tracker_gui: "TrackerGui",
    notification_panel: "NotificationPanel",
) -> None:
    payload = {
        "obs": obs_app.get_settings(),
        "tracker": tracker_gui.get_settings(),
        "notification": notification_panel.get_settings(),
    }

    try:
        APP_SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as error:
        messagebox.showerror("Save Failed", str(error), parent=root)
        return

    messagebox.showinfo(
        "Settings Saved",
        f"Saved program settings to:\n{APP_SETTINGS_PATH.resolve()}",
        parent=root,
    )


def load_app_settings(
    root: tk.Tk,
    obs_app: OBSGroupTogglerApp,
    tracker_gui: "TrackerGui",
    notification_panel: "NotificationPanel",
) -> None:
    if not APP_SETTINGS_PATH.exists():
        messagebox.showwarning(
            "Settings Not Found",
            f"No saved settings found at:\n{APP_SETTINGS_PATH.resolve()}",
            parent=root,
        )
        return

    try:
        payload = json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Settings file must contain a JSON object.")

        obs_payload = payload.get("obs", {})
        tracker_payload = payload.get("tracker", {})
        notification_payload = payload.get("notification", {})

        if isinstance(obs_payload, dict):
            obs_app.apply_settings(obs_payload)
        if isinstance(tracker_payload, dict):
            tracker_gui.apply_settings(tracker_payload)
        if isinstance(notification_payload, dict):
            notification_panel.apply_settings(notification_payload)
    except Exception as error:
        messagebox.showerror("Load Failed", str(error), parent=root)
        return

    messagebox.showinfo(
        "Settings Loaded",
        f"Loaded program settings from:\n{APP_SETTINGS_PATH.resolve()}",
        parent=root,
    )


def build_menu(
    root: tk.Tk,
    obs_app: OBSGroupTogglerApp,
    tracker_gui: "TrackerGui",
    notification_panel: "NotificationPanel",
) -> None:
    menu_bar = tk.Menu(root)
    settings_menu = tk.Menu(menu_bar, tearoff=False)
    settings_menu.add_command(
        label="Save Settings",
        command=lambda: save_app_settings(root, obs_app, tracker_gui, notification_panel),
    )
    settings_menu.add_command(
        label="Load Settings",
        command=lambda: load_app_settings(root, obs_app, tracker_gui, notification_panel),
    )
    menu_bar.add_cascade(label="Settings", menu=settings_menu)
    root.config(menu=menu_bar)


class Mp3Player:
    def __init__(self) -> None:
        self._counter = 0
        self._aliases: list[str] = []

    def play(self, path: Path) -> None:
        self._counter += 1
        alias = f"notification_sound_{self._counter}"
        quoted_path = str(path).replace('"', '""')

        self._mci(f'open "{quoted_path}" type mpegvideo alias {alias}')
        self._mci(f"play {alias}")
        self._aliases.append(alias)

    def close_all(self) -> None:
        for alias in self._aliases:
            self._mci(f"close {alias}", raise_on_error=False)
        self._aliases.clear()

    def _mci(self, command: str, raise_on_error: bool = True) -> None:
        error_code = ctypes.windll.winmm.mciSendStringW(command, None, 0, None)
        if error_code and raise_on_error:
            error_message = ctypes.create_unicode_buffer(255)
            ctypes.windll.winmm.mciGetErrorStringW(error_code, error_message, 255)
            raise RuntimeError(error_message.value)


class NotificationPanel:
    def __init__(self, parent: tk.Misc, root: tk.Tk) -> None:
        self.parent = parent
        self.root = root
        self.audio = Mp3Player()
        self.chroma_key_color = "#00ff00"
        self.notification_image: Optional[tk.PhotoImage] = None
        self.active_popup: Optional[tk.Toplevel] = None
        self.notification_after_id: Optional[str] = None
        self.notification_queue: list[tuple[str, dict[str, Path], Optional[str], str]] = []

        self.duration_seconds = tk.DoubleVar(value=5.0)
        self.message_font_size = tk.IntVar(value=18)
        self.username_font_size = tk.IntVar(value=22)
        self.username_color_name = tk.StringVar(value="Windows XP Blue")
        self.grid_columns = tk.IntVar(value=10)
        self.grid_rows = tk.IntVar(value=12)
        self.show_grid = tk.BooleanVar(value=False)
        self.messages = {
            name: tk.StringVar(
                value="Thank you for the follow. I love you so much"
                if name == "Follower"
                else "Thank you so much for the gift! I promise not to spend it all on snacks <3"
                if name == "Gift"
                else ""
            )
            for name in NOTIFICATIONS
        }
        self.usernames = {name: tk.StringVar(value="") for name in NOTIFICATIONS}

        self.notification_window = self.build_notification_window()
        self.notification_canvas = self.build_notification_canvas()
        self.build_ui()

    def build_notification_window(self) -> tk.Toplevel:
        window = tk.Toplevel(self.root)
        window.title("Stream_notification")
        window.configure(bg=self.chroma_key_color)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self.hide_notification_window)
        return window

    def build_notification_canvas(self) -> tk.Canvas:
        width, height = self.get_default_notification_size()
        canvas = tk.Canvas(
            self.notification_window,
            width=width,
            height=height,
            bg=self.chroma_key_color,
            borderwidth=0,
            highlightthickness=0,
        )
        canvas.pack()
        return canvas

    def get_default_notification_size(self) -> tuple[int, int]:
        for assets in NOTIFICATIONS.values():
            image_path = assets["image"]
            if image_path.exists():
                try:
                    image = tk.PhotoImage(file=image_path)
                except tk.TclError:
                    continue
                return image.width(), image.height()
        return 800, 450

    def build_ui(self) -> None:
        self.parent.columnconfigure(0, weight=1)

        settings = ttk.LabelFrame(self.parent, text="Notification Settings", padding=12)
        settings.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        for column in (1, 3):
            settings.columnconfigure(column, weight=1)

        ttk.Label(settings, text="Duration seconds").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Spinbox(
            settings,
            from_=0.5,
            to=60.0,
            increment=0.5,
            textvariable=self.duration_seconds,
            width=8,
        ).grid(row=0, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(settings, text="Message font size").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        ttk.Spinbox(settings, from_=8, to=96, textvariable=self.message_font_size, width=8).grid(
            row=0, column=3, sticky="w", padx=4, pady=4
        )

        ttk.Label(settings, text="Username font size").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Spinbox(settings, from_=8, to=96, textvariable=self.username_font_size, width=8).grid(
            row=1, column=1, sticky="w", padx=4, pady=4
        )

        ttk.Label(settings, text="Username color").grid(row=1, column=2, sticky="w", padx=4, pady=4)
        ttk.OptionMenu(settings, self.username_color_name, self.username_color_name.get(), *USERNAME_COLORS).grid(
            row=1, column=3, sticky="w", padx=4, pady=4
        )

        ttk.Button(settings, text="Clear Queue", command=self.clear_queue).grid(
            row=2, column=0, sticky="w", padx=4, pady=(8, 4)
        )

        grid_frame = ttk.LabelFrame(self.parent, text="Text Grid", padding=12)
        grid_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        ttk.Label(grid_frame, text="Columns").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Spinbox(grid_frame, from_=1, to=50, textvariable=self.grid_columns, width=8).grid(
            row=0, column=1, sticky="w", padx=4, pady=4
        )
        ttk.Label(grid_frame, text="Rows").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        ttk.Spinbox(grid_frame, from_=1, to=50, textvariable=self.grid_rows, width=8).grid(
            row=0, column=3, sticky="w", padx=4, pady=4
        )
        ttk.Label(grid_frame, text="Username box: 2,4 to 9,4").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=4, pady=(6, 2)
        )
        ttk.Label(grid_frame, text="Message box: 2,6 to 9,7").grid(
            row=2, column=0, columnspan=4, sticky="w", padx=4, pady=2
        )
        ttk.Checkbutton(grid_frame, text="Show placement grid", variable=self.show_grid).grid(
            row=3, column=0, columnspan=4, sticky="w", padx=4, pady=(6, 0)
        )

        rows_frame = ttk.LabelFrame(self.parent, text="Test Notifications", padding=12)
        rows_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        rows_frame.columnconfigure(1, weight=1)

        ttk.Label(rows_frame, text="Message").grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(rows_frame, text="Username").grid(row=0, column=2, sticky="w", padx=4)

        for row_index, (name, assets) in enumerate(NOTIFICATIONS.items(), start=1):
            ttk.Button(
                rows_frame,
                text=f"New {name}",
                command=lambda label=name, item=assets: self.show_notification(label, item),
            ).grid(row=row_index, column=0, sticky="ew", padx=4, pady=4)
            ttk.Entry(rows_frame, textvariable=self.messages[name], width=52).grid(
                row=row_index, column=1, sticky="ew", padx=4, pady=4
            )
            ttk.Entry(rows_frame, textvariable=self.usernames[name], width=24).grid(
                row=row_index, column=2, sticky="ew", padx=4, pady=4
            )

    def get_settings(self) -> dict[str, object]:
        return {
            "duration_seconds": self.duration_seconds.get(),
            "message_font_size": self.message_font_size.get(),
            "username_font_size": self.username_font_size.get(),
            "username_color_name": self.username_color_name.get(),
            "grid_columns": self.grid_columns.get(),
            "grid_rows": self.grid_rows.get(),
            "show_grid": self.show_grid.get(),
            "messages": {
                name: value.get()
                for name, value in self.messages.items()
            },
            "usernames": {
                name: value.get()
                for name, value in self.usernames.items()
            },
        }

    def apply_settings(self, payload: dict[str, object]) -> None:
        self.duration_seconds.set(float(payload.get("duration_seconds", 5.0)))
        self.message_font_size.set(int(payload.get("message_font_size", 18)))
        self.username_font_size.set(int(payload.get("username_font_size", 22)))

        color_name = str(payload.get("username_color_name", "Windows XP Blue"))
        self.username_color_name.set(color_name if color_name in USERNAME_COLORS else "Windows XP Blue")
        self.grid_columns.set(int(payload.get("grid_columns", 10)))
        self.grid_rows.set(int(payload.get("grid_rows", 12)))
        self.show_grid.set(bool(payload.get("show_grid", False)))

        messages = payload.get("messages", {})
        if isinstance(messages, dict):
            for name, message in messages.items():
                if name in self.messages:
                    self.messages[name].set(str(message))

        usernames = payload.get("usernames", {})
        if isinstance(usernames, dict):
            for name, username in usernames.items():
                if name in self.usernames:
                    self.usernames[name].set(str(username))

    def show_notification(
        self,
        name: str,
        assets: dict[str, Path],
        username_override: Optional[str] = None,
        gift_text: str = "",
    ) -> None:
        self.notification_queue.append((name, assets, username_override, gift_text))
        self.process_notification_queue()

    def clear_queue(self) -> None:
        self.notification_queue.clear()

    def process_notification_queue(self) -> None:
        if self.active_popup is not None and self.active_popup.winfo_exists():
            return

        self.active_popup = None
        while self.notification_queue:
            name, assets, username_override, gift_text = self.notification_queue.pop(0)
            if self.open_notification(name, assets, username_override, gift_text):
                return

    def open_notification(
        self,
        name: str,
        assets: dict[str, Path],
        username_override: Optional[str],
        gift_text: str,
    ) -> bool:
        duration_ms = self.get_duration_ms()
        grid_settings = self.get_grid_settings()
        if duration_ms is None or grid_settings is None:
            return False

        image_path = assets["image"]
        sound_path = assets["sound"]
        if not image_path.exists():
            messagebox.showerror("Missing Image", f"Could not find {name} image:\n{image_path}", parent=self.root)
            return False
        if not sound_path.exists():
            messagebox.showerror("Missing Sound", f"Could not find {name} sound:\n{sound_path}", parent=self.root)
            return False

        try:
            self.audio.play(sound_path)
        except RuntimeError as error:
            messagebox.showerror("Sound Error", f"Could not play {name} sound:\n{error}", parent=self.root)

        image = tk.PhotoImage(file=image_path)
        self.notification_image = image
        canvas = self.notification_canvas
        canvas.configure(width=image.width(), height=image.height())
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=self.notification_image)

        self.notification_window.geometry(f"{image.width()}x{image.height()}")
        if not self.notification_window.winfo_viewable():
            self.notification_window.deiconify()
        self.active_popup = self.notification_window

        if self.notification_after_id is not None:
            self.notification_window.after_cancel(self.notification_after_id)
            self.notification_after_id = None

        columns, rows = grid_settings
        if self.show_grid.get():
            self.draw_grid(canvas, image.width(), image.height(), columns, rows)

        self.draw_gift_text(canvas, gift_text, image.width(), image.height(), columns, rows)
        self.draw_message(canvas, name, image.width(), image.height(), columns, rows)
        username_item = self.draw_username(
            canvas,
            name,
            image.width(),
            image.height(),
            columns,
            rows,
            username_override,
        )
        if username_item is not None:
            self.animate_username_color(self.notification_window, canvas, username_item)

        self.notification_after_id = self.notification_window.after(duration_ms, self.clear_notification)
        return True

    def get_duration_ms(self) -> Optional[int]:
        try:
            duration = self.duration_seconds.get()
        except tk.TclError:
            duration = 0
        if duration <= 0:
            messagebox.showerror("Invalid Duration", "Duration must be greater than 0 seconds.", parent=self.root)
            return None
        return int(duration * 1000)

    def get_grid_settings(self) -> Optional[tuple[int, int]]:
        try:
            columns = self.grid_columns.get()
            rows = self.grid_rows.get()
        except tk.TclError:
            columns = rows = 0
        if min(columns, rows) <= 0:
            messagebox.showerror("Invalid Grid", "Grid values must be greater than 0.", parent=self.root)
            return None
        required_columns = max(
            MESSAGE_BOX["end_column"],
            USERNAME_BOX["end_column"],
            GIFT_BOX["end_column"],
        )
        required_rows = max(
            MESSAGE_BOX["end_row"],
            USERNAME_BOX["end_row"],
            GIFT_BOX["end_row"],
        )
        if columns < required_columns or rows < required_rows:
            messagebox.showerror(
                "Invalid Grid",
                "Grid must be at least 9 columns by 7 rows for the text boxes.",
                parent=self.root,
            )
            return None
        return columns, rows

    def draw_grid(self, canvas: tk.Canvas, width: int, height: int, columns: int, rows: int) -> None:
        cell_width = width / columns
        cell_height = height / rows
        for column in range(columns + 1):
            x = round(column * cell_width)
            canvas.create_line(x, 0, x, height, fill="#ff00ff", width=1)
        for row in range(rows + 1):
            y = round(row * cell_height)
            canvas.create_line(0, y, width, y, fill="#ff00ff", width=1)
        for row in range(rows):
            for column in range(columns):
                canvas.create_text(
                    column * cell_width + 4,
                    row * cell_height + 4,
                    anchor="nw",
                    text=f"{column + 1},{row + 1}",
                    fill="#ffffff",
                    font=("Tahoma", 8, "bold"),
                )
        self.draw_box_outline(canvas, MESSAGE_BOX, width, height, columns, rows, "#ffff00")
        self.draw_box_outline(canvas, USERNAME_BOX, width, height, columns, rows, "#00ffff")
        self.draw_box_outline(canvas, GIFT_BOX, width, height, columns, rows, "#ff9900")

    def draw_box_outline(
        self,
        canvas: tk.Canvas,
        box: dict[str, int],
        width: int,
        height: int,
        columns: int,
        rows: int,
        color: str,
    ) -> None:
        left, top, right, bottom = self.get_box_bounds(box, width, height, columns, rows)
        canvas.create_rectangle(left, top, right, bottom, outline=color, width=2)

    def draw_message(self, canvas: tk.Canvas, name: str, width: int, height: int, columns: int, rows: int) -> None:
        message = self.messages[name].get().strip()
        if message:
            self.draw_text_in_box(
                canvas,
                message,
                MESSAGE_BOX,
                width,
                height,
                columns,
                rows,
                "#000000",
                self.get_message_font_size(),
            )

    def draw_gift_text(
        self,
        canvas: tk.Canvas,
        gift_text: str,
        width: int,
        height: int,
        columns: int,
        rows: int,
    ) -> None:
        gift_text = gift_text.strip()
        if gift_text:
            self.draw_text_in_box(
                canvas,
                gift_text,
                GIFT_BOX,
                width,
                height,
                columns,
                rows,
                "#000000",
                self.get_message_font_size(),
            )

    def trigger_tiktok_notification(
        self,
        notification_type: str,
        username: str,
        gift_text: str = "",
    ) -> None:
        assets = NOTIFICATIONS.get(notification_type)
        if assets is None:
            return
        self.show_notification(
            notification_type,
            assets,
            username_override=username,
            gift_text=gift_text,
        )

    def draw_username(
        self,
        canvas: tk.Canvas,
        name: str,
        width: int,
        height: int,
        columns: int,
        rows: int,
        username_override: Optional[str] = None,
    ) -> Optional[int]:
        username = (username_override or self.usernames[name].get()).strip()
        if not username:
            return None
        return self.draw_text_in_box(
            canvas,
            username,
            USERNAME_BOX,
            width,
            height,
            columns,
            rows,
            self.get_username_color(),
            self.get_username_font_size(),
        )

    def draw_text_in_box(
        self,
        canvas: tk.Canvas,
        text: str,
        box: dict[str, int],
        width: int,
        height: int,
        columns: int,
        rows: int,
        color: str,
        font_size: int,
    ) -> int:
        left, top, right, bottom = self.get_box_bounds(box, width, height, columns, rows)
        text_width = max(1, int(right - left - 12))
        return canvas.create_text(
            (left + right) / 2,
            (top + bottom) / 2,
            text=text,
            fill=color,
            font=("Tahoma", font_size, "bold"),
            justify="center",
            width=text_width,
        )

    def get_message_font_size(self) -> int:
        try:
            font_size = self.message_font_size.get()
        except tk.TclError:
            font_size = 18
        return max(1, font_size)

    def get_username_font_size(self) -> int:
        try:
            font_size = self.username_font_size.get()
        except tk.TclError:
            font_size = 22
        return max(1, font_size)

    def get_username_color(self) -> str:
        return USERNAME_COLORS.get(self.username_color_name.get(), "#245edb")

    def animate_username_color(
        self,
        popup: tk.Toplevel,
        canvas: tk.Canvas,
        username_item: int,
        color_index: int = 0,
    ) -> None:
        if not popup.winfo_exists() or not canvas.winfo_exists():
            return
        if not canvas.find_withtag(username_item):
            return
        colors = list(USERNAME_COLORS.values())
        canvas.itemconfigure(username_item, fill=colors[color_index % len(colors)])
        popup.after(500, lambda: self.animate_username_color(popup, canvas, username_item, color_index + 1))

    def get_box_bounds(
        self,
        box: dict[str, int],
        width: int,
        height: int,
        columns: int,
        rows: int,
    ) -> tuple[float, float, float, float]:
        cell_width = width / columns
        cell_height = height / rows
        left = (box["start_column"] - 1) * cell_width
        top = (box["start_row"] - 1) * cell_height
        right = box["end_column"] * cell_width
        bottom = box["end_row"] * cell_height
        return left, top, right, bottom

    def clear_notification(self) -> None:
        self.notification_after_id = None
        self.notification_canvas.delete("all")
        self.notification_image = None
        self.active_popup = None
        self.root.after(50, self.process_notification_queue)

    def hide_notification_window(self) -> None:
        self.clear_queue()
        if self.notification_after_id is not None:
            self.notification_window.after_cancel(self.notification_after_id)
            self.notification_after_id = None
        self.notification_canvas.delete("all")
        self.notification_image = None
        self.active_popup = None
        self.notification_window.withdraw()

    def close(self) -> None:
        self.notification_queue.clear()
        if self.notification_after_id is not None:
            self.notification_window.after_cancel(self.notification_after_id)
            self.notification_after_id = None
        if self.notification_window.winfo_exists():
            self.notification_window.destroy()
        self.audio.close_all()


class TrackerGui:
    def __init__(self, parent: tk.Misc, root: tk.Tk, connect_parent: Optional[tk.Misc] = None) -> None:
        self.parent = parent
        self.root = root
        self.connect_parent = connect_parent
        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.worker_loop: Optional[asyncio.AbstractEventLoop] = None
        self.worker_tracker: Optional[StreamPointsTracker] = None
        self.worker_running = False
        self.obs_app: Optional[OBSGroupTogglerApp] = None
        self.notification_panel: Optional[NotificationPanel] = None
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
        self.like_multiplier_var = tk.StringVar(value="10")
        self.gift_multiplier_var = tk.StringVar(value="0")
        self.save_every_var = tk.StringVar(value="15")
        self.status_var = tk.StringVar(value="Idle")

        self.build_ui()
        if self.connect_parent is not None:
            self.build_connect_ui(self.connect_parent)
        self.populate_commands_text()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self.process_events)
        self.root.after(500, self.blink_request_cursor)

    def build_requests_window(self) -> tk.Toplevel:
        window = tk.Toplevel(self.root)
        window.title("Stream Requests")
        window.geometry("432x240")
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
        window.geometry("432x275")
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

        ttk.Label(controls, text="Points File").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.points_file_var).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
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

        ttk.Label(controls, text="Likes Per Point").grid(
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
        actions.columnconfigure(2, weight=1)

        ttk.Button(actions, text="Clear Log", command=self.clear_log).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Reset Points File", command=self.reset_points_file).grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Button(actions, text="Edit Selected Points", command=self.edit_selected_points).grid(
            row=0, column=2, padx=(0, 8)
        )

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

    def build_connect_ui(self, parent: tk.Misc) -> None:
        tracker_frame = ttk.LabelFrame(parent, text="TikTok Live Tracker", padding=12)
        tracker_frame.pack(fill="x", padx=12, pady=(0, 12))
        tracker_frame.columnconfigure(1, weight=1)

        ttk.Label(tracker_frame, text="Username").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(tracker_frame, textvariable=self.username_var).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )

        self.start_button = ttk.Button(
            tracker_frame,
            text="Start Tracking",
            command=self.start_tracking,
        )
        self.start_button.grid(row=0, column=2, padx=(8, 4), pady=4)

        self.stop_button = ttk.Button(
            tracker_frame,
            text="Stop Tracking",
            command=self.stop_tracking,
            state="disabled",
        )
        self.stop_button.grid(row=0, column=3, padx=4, pady=4)

        ttk.Label(tracker_frame, text="Status:").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(tracker_frame, textvariable=self.status_var).grid(
            row=1, column=1, columnspan=3, sticky="w", padx=4, pady=4
        )

    def get_settings(self) -> dict[str, object]:
        return {
            "username": self.username_var.get(),
            "points_file": self.points_file_var.get(),
            "view_points": self.view_points_var.get(),
            "view_interval": self.view_interval_var.get(),
            "active_window": self.active_window_var.get(),
            "likes_per_point": self.like_multiplier_var.get(),
            "gift_multiplier": self.gift_multiplier_var.get(),
            "save_every": self.save_every_var.get(),
        }

    def apply_settings(self, payload: dict[str, object]) -> None:
        self.username_var.set(str(payload.get("username", "")))
        self.points_file_var.set(str(payload.get("points_file", "stream_points.json")))
        self.view_points_var.set(str(payload.get("view_points", "10")))
        self.view_interval_var.set(str(payload.get("view_interval", "60")))
        self.active_window_var.set(str(payload.get("active_window", "180")))
        self.like_multiplier_var.set(str(payload.get("likes_per_point", "10")))
        self.gift_multiplier_var.set(str(payload.get("gift_multiplier", "0")))
        self.save_every_var.set(str(payload.get("save_every", "15")))

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
            "Points:",
            "1 point per minute watched",
            "1 point per 10 likes",
            "25 points per share",
            "Gifts: no points right now",
            "",
            "Commands:",
            "!showpoints",
            "Check your points",
            "",
            "!closewindow - 10 points",
            "Close 1 window",
            "",
            "!closeallwindows - 50 points",
            "Close all windows",
            "",
            "!spawm - 10 points",
            "Show 1 SPAM window",
            "",
            "!spawmall - 50 points",
            "Show all SPAM windows",
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

    def parse_non_negative_int(self, raw_value: str, field_name: str) -> int:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a whole number.") from exc

        if value < 0:
            raise ValueError(f"{field_name} must be 0 or greater.")

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
            likes_per_point=self.parse_positive_int(
                self.like_multiplier_var.get(), "Like Multiplier"
            ),
            gift_multiplier=self.parse_non_negative_int(
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
            on_notification=lambda payload: self.event_queue.put(("notification", payload)),
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

        redeemer_name = viewer.nickname or viewer.unique_id

        try:
            if command == "!closewindow":
                success, obs_message = self.obs_app.hide_random_reward_action()
            elif command == "!closeallwindows":
                success, obs_message, _ = self.obs_app.hide_all_reward_action()
            elif command in {"!spam", "!spawm"}:
                success, obs_message = self.obs_app.show_random_spam_action(redeemer_name)
            elif command in {"!spamall", "!spawmall"}:
                success, obs_message, _ = self.obs_app.show_all_spam_action(redeemer_name)
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

    def handle_notification_request(self, payload: object) -> None:
        if self.notification_panel is None or not isinstance(payload, dict):
            return

        notification_type = str(payload.get("type", ""))
        username = str(payload.get("nickname") or payload.get("unique_id") or "")
        gift_name = str(payload.get("gift_name", "")).strip()
        repeat_count = payload.get("repeat_count", "")
        gift_text = ""
        if gift_name:
            try:
                amount = int(repeat_count)
            except (TypeError, ValueError):
                amount = 1
            gift_text = f"{gift_name} x{max(amount, 1)}"

        if not notification_type:
            return

        self.notification_panel.trigger_tiktok_notification(notification_type, username, gift_text)
        self.append_log(f"Notification shown: {notification_type} for {username}")

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
                elif event_type == "notification":
                    self.handle_notification_request(payload)
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

        if self.notification_panel is not None:
            self.notification_panel.close()
        self.root.destroy()

    def finish_close(self) -> None:
        if self.worker_running:
            self.root.after(250, self.finish_close)
            return
        if self.requests_window.winfo_exists():
            self.requests_window.destroy()
        if self.commands_window.winfo_exists():
            self.commands_window.destroy()
        if self.notification_panel is not None:
            self.notification_panel.close()
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

    connect_tab = ttk.Frame(notebook)
    obs_tab = ttk.Frame(notebook)
    window_presets_tab = ttk.Frame(notebook)
    points_tab = ttk.Frame(notebook)
    notification_tab = ttk.Frame(notebook)

    notebook.add(connect_tab, text="Connect")
    notebook.add(obs_tab, text="OBS Controls")
    notebook.add(window_presets_tab, text="Window Presets")
    notebook.add(points_tab, text="Stream Points")
    notebook.add(notification_tab, text="Notification")

    obs_app = OBSGroupTogglerApp(obs_tab, connection_parent=connect_tab)
    window_presets_app = OBSWindowPresetApp(window_presets_tab, obs_app)
    tracker_gui = TrackerGui(points_tab, root, connect_parent=connect_tab)
    notification_panel = NotificationPanel(notification_tab, root)
    tracker_gui.obs_app = obs_app
    tracker_gui.notification_panel = notification_panel
    build_menu(root, obs_app, tracker_gui, notification_panel)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
