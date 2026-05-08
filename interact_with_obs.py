import tkinter as tk
from tkinter import ttk, messagebox
import random
import obsws_python as obs

REWARD_ITEMS = [
    "Groupe_camera",
    "Groupe_game_full",
    "Groupe_game_half",
    "Media_Player",
    "Pixel_Sly",
    "Stream_requests",
    "Stream_rewards",
]

SPAM_ITEMS = [
    "SPAM1",
    "SPAM2",
    "SPAM3",
    "SPAM4",
    "SPAM5",
]

SPAM_GROUP_NAME = "SPAM"

CONTROLLED_ITEM_COLUMNS = [
    ("Reward Windows", REWARD_ITEMS),
    ("Spam Windows", SPAM_ITEMS),
]

ALL_CONTROLLED_ITEMS = REWARD_ITEMS + SPAM_ITEMS



class OBSGroupTogglerApp:
    def __init__(self, parent):
        self.parent = parent

        self.client = None

        self.host_var = tk.StringVar(value="localhost")
        self.port_var = tk.StringVar(value="4455")
        self.password_var = tk.StringVar(value="")

        self.status_var = tk.StringVar(value="Not connected")
        self.scene_var = tk.StringVar(value="Scene: -")
        self.item_widgets = {}

        self.build_ui()

    def build_ui(self):
        main = ttk.Frame(self.parent, padding=12)
        main.pack(fill="both", expand=True)

        conn_frame = ttk.LabelFrame(main, text="OBS Connection", padding=10)
        conn_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(conn_frame, text="Host").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(conn_frame, textvariable=self.host_var, width=18).grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(conn_frame, text="Port").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(conn_frame, textvariable=self.port_var, width=18).grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(conn_frame, text="Password").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(conn_frame, textvariable=self.password_var, width=18, show="*").grid(row=2, column=1, sticky="w", pady=4)

        ttk.Button(conn_frame, text="Connect", command=self.connect_obs).grid(
            row=0, column=2, rowspan=3, padx=(12, 0), sticky="ns"
        )

        status_frame = ttk.LabelFrame(main, text="Status", padding=10)
        status_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor="w")
        ttk.Label(status_frame, textvariable=self.scene_var).pack(anchor="w", pady=(6, 0))

        items_frame = ttk.LabelFrame(main, text="Items Controlled", padding=10)
        items_frame.pack(fill="both", expand=True, pady=(0, 10))
        items_frame.columnconfigure(0, weight=1)
        items_frame.columnconfigure(1, weight=1)

        for column_index, (column_title, items) in enumerate(CONTROLLED_ITEM_COLUMNS):
            column_frame = ttk.LabelFrame(items_frame, text=column_title, padding=8)
            column_frame.grid(row=0, column=column_index, sticky="nsew", padx=6)
            column_frame.columnconfigure(0, weight=1)

            for item in items:
                row = ttk.Frame(column_frame)
                row.pack(fill="x", pady=4)

                indicator = tk.Canvas(row, width=14, height=14, highlightthickness=0)
                indicator.pack(side="left", padx=(0, 8))
                indicator_oval = indicator.create_oval(2, 2, 12, 12, fill="gray", outline="")

                ttk.Label(row, text=item, width=24).pack(side="left")

                item_status_var = tk.StringVar(value="Unknown")
                ttk.Label(row, textvariable=item_status_var, width=12).pack(side="left", padx=(0, 8))

                toggle_button = ttk.Button(
                    row,
                    text="Toggle",
                    command=lambda item_name=item: self.toggle_single_item(item_name),
                    state="disabled",
                )
                toggle_button.pack(side="right")

                self.item_widgets[item] = {
                    "indicator": indicator,
                    "indicator_oval": indicator_oval,
                    "status_var": item_status_var,
                    "toggle_button": toggle_button,
                }

        button_frame = ttk.Frame(main)
        button_frame.pack(fill="x")

        self.hide_all_button = ttk.Button(button_frame, text="Hide Items", command=self.hide_items, state="disabled")
        self.hide_all_button.pack(fill="x", pady=(0, 8))

        self.hide_random_button = ttk.Button(
            button_frame,
            text="Hide Random Item",
            command=self.hide_random_item,
            state="disabled",
        )
        self.hide_random_button.pack(fill="x")

    def connect_obs(self):
        host = self.host_var.get().strip()
        password = self.password_var.get()
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Port", "Port must be a number.")
            return

        try:
            self.client = obs.ReqClient(
                host=host,
                port=port,
                password=password,
                timeout=3,
            )

            scene_name = self.get_current_scene_name()
            self.status_var.set("Connected to OBS")
            self.scene_var.set(f"Scene: {scene_name}")
            self.set_controls_state("normal")
            self.refresh_items_state(scene_name)
        except Exception as e:
            self.client = None
            self.status_var.set("Connection failed")
            self.scene_var.set("Scene: -")
            self.set_controls_state("disabled")
            self.reset_item_indicators()
            messagebox.showerror("Connection Error", f"Could not connect to OBS.\n\n{e}")

    def get_current_scene_name(self):
        if not self.client:
            raise RuntimeError("Not connected to OBS.")

        resp = self.client.get_current_program_scene()
        return resp.current_program_scene_name

    def get_scene_items_by_name(self, scene_name):
        """
        Returns a dict:
        {
            "ItemName": {
                "sceneItemId": 12,
                "sceneItemEnabled": True,
                "containerName": "Scene or Group Name",
            },
            ...
        }
        """
        result = {}
        scene_resp = self.client.get_scene_item_list(scene_name)

        for item in scene_resp.scene_items:
            item_name = item.get("sourceName")
            item_id = item.get("sceneItemId")
            item_enabled = item.get("sceneItemEnabled")

            if item_name in ALL_CONTROLLED_ITEMS:
                result[item_name] = {
                    "sceneItemId": item_id,
                    "sceneItemEnabled": item_enabled,
                    "containerName": scene_name,
                }

        if any(item_name not in result for item_name in SPAM_ITEMS):
            try:
                group_resp = self.client.get_group_scene_item_list(SPAM_GROUP_NAME)
            except Exception:
                group_resp = None

            if group_resp is not None:
                for item in group_resp.scene_items:
                    item_name = item.get("sourceName")
                    item_id = item.get("sceneItemId")
                    item_enabled = item.get("sceneItemEnabled")

                    if item_name in SPAM_ITEMS:
                        result[item_name] = {
                            "sceneItemId": item_id,
                            "sceneItemEnabled": item_enabled,
                            "containerName": SPAM_GROUP_NAME,
                        }

        return result

    def set_items_visibility(self, visible):
        if not self.client:
            raise RuntimeError("Not connected to OBS.")

        scene_name = self.get_current_scene_name()
        items = self.get_scene_items_by_name(scene_name)

        missing = [name for name in REWARD_ITEMS if name not in items]

        for item_name in REWARD_ITEMS:
            info = items.get(item_name)
            if not info:
                continue

            self.client.set_scene_item_enabled(
                scene_name=info["containerName"],
                item_id=info["sceneItemId"],
                enabled=visible,
            )

        self.scene_var.set(f"Scene: {scene_name}")
        self.refresh_items_state(scene_name)

        return missing

    def get_reward_items_with_state(self):
        scene_name = self.get_current_scene_name()
        items = self.get_scene_items_by_name(scene_name)
        reward_items = {
            item_name: items[item_name]
            for item_name in REWARD_ITEMS
            if item_name in items
        }
        missing = [name for name in REWARD_ITEMS if name not in reward_items]
        return scene_name, reward_items, missing

    def set_spam_items_visibility(self, visible):
        if not self.client:
            raise RuntimeError("Not connected to OBS.")

        scene_name = self.get_current_scene_name()
        items = self.get_scene_items_by_name(scene_name)

        missing = [name for name in SPAM_ITEMS if name not in items]

        for item_name in SPAM_ITEMS:
            info = items.get(item_name)
            if not info:
                continue

            self.client.set_scene_item_enabled(
                scene_name=info["containerName"],
                item_id=info["sceneItemId"],
                enabled=visible,
            )

        self.scene_var.set(f"Scene: {scene_name}")
        self.refresh_items_state(scene_name)

        return missing

    def get_spam_items_with_state(self):
        scene_name = self.get_current_scene_name()
        items = self.get_scene_items_by_name(scene_name)
        spam_items = {
            item_name: items[item_name]
            for item_name in SPAM_ITEMS
            if item_name in items
        }
        missing = [name for name in SPAM_ITEMS if name not in spam_items]
        return scene_name, spam_items, missing

    def set_single_item_visibility(self, scene_name, item_name, visible):
        items = self.get_scene_items_by_name(scene_name)
        item_info = items.get(item_name)

        if not item_info:
            return False

        self.client.set_scene_item_enabled(
            scene_name=item_info["containerName"],
            item_id=item_info["sceneItemId"],
            enabled=visible,
        )
        self.refresh_items_state(scene_name)
        return True

    def set_spam_redeemer_name(self, spam_item_name, redeemer_name):
        if not self.client:
            raise RuntimeError("Not connected to OBS.")

        text_source_name = f"{spam_item_name}_text"
        self.client.set_input_settings(
            name=text_source_name,
            settings={"text": redeemer_name},
            overlay=True,
        )

    def set_controls_state(self, state):
        self.hide_all_button.config(state=state)
        self.hide_random_button.config(state=state)
        for widgets in self.item_widgets.values():
            widgets["toggle_button"].config(state=state)

    def update_indicator(self, item_name, color):
        widgets = self.item_widgets[item_name]
        widgets["indicator"].itemconfig(widgets["indicator_oval"], fill=color)

    def reset_item_indicators(self):
        for item_name, widgets in self.item_widgets.items():
            widgets["status_var"].set("Unknown")
            self.update_indicator(item_name, "gray")

    def refresh_items_state(self, scene_name=None):
        if not self.client:
            self.reset_item_indicators()
            return

        if scene_name is None:
            scene_name = self.get_current_scene_name()

        items = self.get_scene_items_by_name(scene_name)
        self.scene_var.set(f"Scene: {scene_name}")

        for item_name in ALL_CONTROLLED_ITEMS:
            item_info = items.get(item_name)
            widgets = self.item_widgets[item_name]

            if not item_info:
                widgets["status_var"].set("Not found")
                self.update_indicator(item_name, "red")
                continue

            if item_info["sceneItemEnabled"]:
                widgets["status_var"].set("Enabled")
                self.update_indicator(item_name, "green")
            else:
                widgets["status_var"].set("Disabled")
                self.update_indicator(item_name, "red")

    def toggle_single_item(self, item_name):
        try:
            scene_name = self.get_current_scene_name()
            items = self.get_scene_items_by_name(scene_name)
            item_info = items.get(item_name)

            if not item_info:
                self.refresh_items_state(scene_name)
                messagebox.showwarning(
                    "Item Not Found",
                    f'"{item_name}" was not found in the current scene.',
                )
                return

            new_state = not item_info["sceneItemEnabled"]
            self.set_single_item_visibility(scene_name, item_name, new_state)
            self.status_var.set(f'{item_name} {"enabled" if new_state else "disabled"}')
        except Exception as e:
            messagebox.showerror("OBS Error", f"Failed to toggle item.\n\n{e}")

    def hide_items(self):
        try:
            success, message, missing = self.hide_all_reward_action()
            self.status_var.set(message)

            if success and missing:
                messagebox.showwarning(
                    "Some Items Not Found",
                    "These items were not found in the current scene:\n\n" + "\n".join(missing),
                )
        except Exception as e:
            messagebox.showerror("OBS Error", f"Failed to hide items.\n\n{e}")

    def hide_random_item(self):
        try:
            success, message = self.hide_random_reward_action()
            self.status_var.set(message)
        except Exception as e:
            messagebox.showerror("OBS Error", f"Failed to hide a random item.\n\n{e}")

    def hide_all_reward_action(self):
        scene_name, reward_items, missing = self.get_reward_items_with_state()
        enabled_items = [
            name for name, info in reward_items.items() if info["sceneItemEnabled"]
        ]

        if not enabled_items:
            self.scene_var.set(f"Scene: {scene_name}")
            self.refresh_items_state(scene_name)
            return False, "No enabled items available", missing

        for item_name in enabled_items:
            item_info = reward_items[item_name]
            self.client.set_scene_item_enabled(
                scene_name=item_info["containerName"],
                item_id=item_info["sceneItemId"],
                enabled=False,
            )

        self.scene_var.set(f"Scene: {scene_name}")
        self.refresh_items_state(scene_name)
        return True, "Items hidden", missing

    def hide_random_reward_action(self):
        scene_name = self.get_current_scene_name()
        items = self.get_scene_items_by_name(scene_name)
        available_items = [
            name for name in REWARD_ITEMS if name in items and items[name]["sceneItemEnabled"]
        ]

        if not available_items:
            self.scene_var.set(f"Scene: {scene_name}")
            self.refresh_items_state(scene_name)
            return False, "No enabled items available"

        item_name = random.choice(available_items)
        self.set_single_item_visibility(scene_name, item_name, False)
        return True, f"Random item hidden: {item_name}"

    def show_all_spam_action(self, redeemer_name=None):
        scene_name, spam_items, missing = self.get_spam_items_with_state()
        disabled_items = [
            name for name, info in spam_items.items() if not info["sceneItemEnabled"]
        ]

        if not disabled_items:
            self.scene_var.set(f"Scene: {scene_name}")
            self.refresh_items_state(scene_name)
            return False, "No disabled spam items available", missing

        display_name = (redeemer_name or "").strip()
        if display_name:
            for item_name in disabled_items:
                self.set_spam_redeemer_name(item_name, display_name)

        for item_name in disabled_items:
            item_info = spam_items[item_name]
            self.client.set_scene_item_enabled(
                scene_name=item_info["containerName"],
                item_id=item_info["sceneItemId"],
                enabled=True,
            )

        self.scene_var.set(f"Scene: {scene_name}")
        self.refresh_items_state(scene_name)
        return True, "Spam windows enabled", missing

    def show_random_spam_action(self, redeemer_name=None):
        scene_name = self.get_current_scene_name()
        items = self.get_scene_items_by_name(scene_name)
        available_items = [
            name for name in SPAM_ITEMS if name in items and not items[name]["sceneItemEnabled"]
        ]

        if not available_items:
            self.scene_var.set(f"Scene: {scene_name}")
            self.refresh_items_state(scene_name)
            return False, "No disabled spam items available"

        item_name = random.choice(available_items)
        display_name = (redeemer_name or "").strip()
        if display_name:
            self.set_spam_redeemer_name(item_name, display_name)
        self.set_single_item_visibility(scene_name, item_name, True)
        return True, f"Spam window enabled: {item_name}"


if __name__ == "__main__":
    root = tk.Tk()
    root.title("OBS Group Toggle")
    root.geometry("860x600")
    root.resizable(False, False)
    app = OBSGroupTogglerApp(root)
    root.mainloop()
