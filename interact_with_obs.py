import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
import random
import obsws_python as obs

REWARD_ITEMS = [
    "Guest_group",
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
WINDOW_PRESET_ITEMS = [
    "Groupe_game_full",
    "Groupe_game_half",
]
WINDOW_PRESETS_PATH = Path("obs_window_presets.json")
SETTABLE_TRANSFORM_KEYS = {
    "alignment",
    "boundsAlignment",
    "boundsHeight",
    "boundsType",
    "boundsWidth",
    "cropBottom",
    "cropLeft",
    "cropRight",
    "cropTop",
    "positionX",
    "positionY",
    "rotation",
    "scaleX",
    "scaleY",
}

CONTROLLED_ITEM_COLUMNS = [
    ("Reward Windows", REWARD_ITEMS),
    ("Spam Windows", SPAM_ITEMS),
]

ALL_CONTROLLED_ITEMS = REWARD_ITEMS + SPAM_ITEMS


class OBSWindowPresetApp:
    def __init__(self, parent, obs_app):
        self.parent = parent
        self.obs_app = obs_app
        self.presets = []
        self.name_vars = []
        self.status_var = tk.StringVar(value="Ready")
        self.presets_frame = None

        self.load_presets()
        self.build_ui()

    def build_ui(self):
        main = ttk.Frame(self.parent, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        controls = ttk.LabelFrame(main, text="Window Presets", padding=10)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        controls.columnconfigure(1, weight=1)

        ttk.Button(controls, text="Add", command=self.add_preset).grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        ttk.Label(
            controls,
            text="Saves group placement plus child text, image, and game capture settings.",
        ).grid(row=0, column=1, sticky="w")

        list_frame = ttk.LabelFrame(main, text="Saved Presets", padding=10)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.presets_frame = ttk.Frame(canvas)
        self.presets_frame.columnconfigure(0, weight=1)

        self.presets_frame.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas_window = canvas.create_window((0, 0), window=self.presets_frame, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(canvas_window, width=event.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        ttk.Label(main, textvariable=self.status_var).grid(row=2, column=0, sticky="w")
        self.refresh_preset_rows()

    def load_presets(self):
        if not WINDOW_PRESETS_PATH.exists():
            self.presets = []
            return

        try:
            payload = json.loads(WINDOW_PRESETS_PATH.read_text(encoding="utf-8"))
            presets = payload.get("presets", []) if isinstance(payload, dict) else []
            self.presets = [
                preset
                for preset in presets
                if isinstance(preset, dict)
                and isinstance(preset.get("items"), dict)
                and isinstance(preset.get("name"), str)
            ]
        except Exception:
            self.presets = []

    def save_presets(self):
        payload = {"presets": self.presets}
        WINDOW_PRESETS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_client(self):
        client = getattr(self.obs_app, "client", None)
        if client is None:
            raise RuntimeError("Not connected to OBS.")
        return client

    def capture_item_state(self, scene_name, item_name):
        client = self.get_client()
        items = self.obs_app.get_scene_items_by_name(scene_name)
        item_info = items.get(item_name)
        if not item_info:
            return None

        container_name = item_info["containerName"]
        item_id = item_info["sceneItemId"]
        transform_resp = client.get_scene_item_transform(
            scene_name=container_name,
            item_id=item_id,
        )

        state = {
            "containerName": container_name,
            "sceneItemEnabled": bool(item_info.get("sceneItemEnabled")),
            "sceneItemTransform": dict(transform_resp.scene_item_transform),
        }

        try:
            state["sceneItemLocked"] = bool(
                client.get_scene_item_locked(scene_name=container_name, item_id=item_id).scene_item_locked
            )
        except Exception:
            pass

        try:
            state["sceneItemBlendMode"] = client.get_scene_item_blend_mode(
                scene_name=container_name,
                item_id=item_id,
            ).scene_item_blend_mode
        except Exception:
            pass

        try:
            state["sceneItemIndex"] = int(
                client.get_scene_item_index(scene_name=container_name, item_id=item_id).scene_item_index
            )
        except Exception:
            pass

        state["groupItems"] = self.capture_group_items(item_name)

        return state

    def capture_group_items(self, group_name):
        client = self.get_client()
        group_items = []

        try:
            group_resp = client.get_group_scene_item_list(group_name)
        except Exception:
            return group_items

        for item in group_resp.scene_items:
            source_name = item.get("sourceName")
            item_id = item.get("sceneItemId")
            if not source_name or item_id is None:
                continue

            child_state = {
                "sourceName": source_name,
                "sceneItemEnabled": bool(item.get("sceneItemEnabled")),
            }

            try:
                transform_resp = client.get_scene_item_transform(
                    scene_name=group_name,
                    item_id=item_id,
                )
                child_state["sceneItemTransform"] = dict(transform_resp.scene_item_transform)
            except Exception:
                pass

            try:
                settings_resp = client.get_input_settings(source_name)
                child_state["inputKind"] = settings_resp.input_kind
                child_state["inputSettings"] = dict(settings_resp.input_settings)
            except Exception:
                pass

            group_items.append(child_state)

        return group_items

    def add_preset(self):
        try:
            scene_name = self.obs_app.get_current_scene_name()
            items = {}
            missing = []

            for item_name in WINDOW_PRESET_ITEMS:
                state = self.capture_item_state(scene_name, item_name)
                if state is None:
                    missing.append(item_name)
                else:
                    items[item_name] = state

            if missing:
                messagebox.showwarning(
                    "Items Not Found",
                    "These items were not found in the current scene:\n\n" + "\n".join(missing),
                    parent=self.parent,
                )

            if not items:
                self.status_var.set("No preset saved")
                return

            preset_number = len(self.presets) + 1
            self.presets.append(
                {
                    "name": f"Preset {preset_number}",
                    "sceneName": scene_name,
                    "version": 2,
                    "items": items,
                }
            )
            self.save_presets()
            self.refresh_preset_rows()
            self.status_var.set(f"Preset {preset_number} saved")
        except Exception as error:
            messagebox.showerror("Preset Error", f"Failed to add preset.\n\n{error}", parent=self.parent)

    def refresh_preset_rows(self):
        if self.presets_frame is None:
            return

        for child in self.presets_frame.winfo_children():
            child.destroy()

        self.name_vars = []

        if not self.presets:
            ttk.Label(self.presets_frame, text="No presets saved yet.").grid(
                row=0,
                column=0,
                sticky="w",
                padx=4,
                pady=4,
            )
            return

        for row_index, preset in enumerate(self.presets):
            row = ttk.Frame(self.presets_frame)
            row.grid(row=row_index, column=0, sticky="ew", pady=4)
            row.columnconfigure(0, weight=1)

            name_var = tk.StringVar(value=str(preset.get("name", f"Preset {row_index + 1}")))
            self.name_vars.append(name_var)

            entry = ttk.Entry(row, textvariable=name_var)
            entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
            entry.bind("<FocusOut>", lambda _event, index=row_index: self.rename_preset(index))
            entry.bind("<Return>", lambda _event, index=row_index: self.rename_preset(index))

            ttk.Button(row, text="Set", command=lambda index=row_index: self.set_preset(index)).grid(
                row=0,
                column=1,
                sticky="e",
                padx=(0, 8),
            )
            ttk.Button(row, text="Remove", command=lambda index=row_index: self.remove_preset(index)).grid(
                row=0,
                column=2,
                sticky="e",
            )

    def rename_preset(self, index):
        if index >= len(self.presets) or index >= len(self.name_vars):
            return

        new_name = self.name_vars[index].get().strip() or f"Preset {index + 1}"
        self.name_vars[index].set(new_name)
        self.presets[index]["name"] = new_name

        try:
            self.save_presets()
            self.status_var.set(f"Renamed preset: {new_name}")
        except Exception as error:
            messagebox.showerror("Preset Error", f"Failed to save preset name.\n\n{error}", parent=self.parent)

    def remove_preset(self, index):
        if index >= len(self.presets):
            return

        preset_name = str(self.presets[index].get("name", f"Preset {index + 1}"))
        confirmed = messagebox.askyesno(
            "Remove Preset",
            f'Remove "{preset_name}"?',
            parent=self.parent,
        )
        if not confirmed:
            return

        try:
            del self.presets[index]
            self.save_presets()
            self.refresh_preset_rows()
            self.status_var.set(f"Removed preset: {preset_name}")
        except Exception as error:
            messagebox.showerror("Preset Error", f"Failed to remove preset.\n\n{error}", parent=self.parent)

    def get_settable_transform(self, transform):
        settable_transform = {
            key: value
            for key, value in transform.items()
            if key in SETTABLE_TRANSFORM_KEYS
        }

        for bounds_key in ("boundsWidth", "boundsHeight"):
            try:
                bounds_value = float(settable_transform.get(bounds_key, 1))
            except (TypeError, ValueError):
                bounds_value = 0

            if bounds_value < 1:
                settable_transform.pop(bounds_key, None)

        return settable_transform

    def get_group_items_by_source_name(self, group_name):
        client = self.get_client()
        result = {}

        try:
            group_resp = client.get_group_scene_item_list(group_name)
        except Exception:
            return result

        for item in group_resp.scene_items:
            source_name = item.get("sourceName")
            item_id = item.get("sceneItemId")
            if source_name and item_id is not None:
                result[source_name] = {
                    "sceneItemId": item_id,
                    "sceneItemEnabled": item.get("sceneItemEnabled"),
                }

        return result

    def restore_group_items(self, group_name, saved_group_items):
        if not isinstance(saved_group_items, list):
            return []

        client = self.get_client()
        current_group_items = self.get_group_items_by_source_name(group_name)
        missing = []

        for saved_child in saved_group_items:
            if not isinstance(saved_child, dict):
                continue

            source_name = str(saved_child.get("sourceName", "")).strip()
            if not source_name:
                continue

            current_child = current_group_items.get(source_name)
            if not current_child:
                missing.append(source_name)
                continue

            input_settings = saved_child.get("inputSettings")
            if isinstance(input_settings, dict):
                client.set_input_settings(
                    name=source_name,
                    settings=input_settings,
                    overlay=False,
                )

            item_id = current_child["sceneItemId"]
            transform = saved_child.get("sceneItemTransform", {})
            if isinstance(transform, dict):
                settable_transform = self.get_settable_transform(transform)
                client.set_scene_item_transform(
                    scene_name=group_name,
                    item_id=item_id,
                    transform=settable_transform,
                )

            client.set_scene_item_enabled(
                scene_name=group_name,
                item_id=item_id,
                enabled=bool(saved_child.get("sceneItemEnabled", True)),
            )

        return missing

    def set_preset(self, index):
        if index >= len(self.presets):
            return

        try:
            client = self.get_client()
            scene_name = self.obs_app.get_current_scene_name()
            current_items = self.obs_app.get_scene_items_by_name(scene_name)
            preset = self.presets[index]
            missing = []
            outdated = []

            for item_name in WINDOW_PRESET_ITEMS:
                saved_state = preset.get("items", {}).get(item_name)
                current_info = current_items.get(item_name)

                if not isinstance(saved_state, dict) or not current_info:
                    missing.append(item_name)
                    continue

                container_name = current_info["containerName"]
                item_id = current_info["sceneItemId"]
                transform = saved_state.get("sceneItemTransform", {})

                if isinstance(transform, dict):
                    settable_transform = self.get_settable_transform(transform)
                    client.set_scene_item_transform(
                        scene_name=container_name,
                        item_id=item_id,
                        transform=settable_transform,
                    )

                if "sceneItemBlendMode" in saved_state:
                    client.set_scene_item_blend_mode(
                        scene_name=container_name,
                        item_id=item_id,
                        blend=saved_state["sceneItemBlendMode"],
                    )

                if "sceneItemLocked" in saved_state:
                    client.set_scene_item_locked(
                        scene_name=container_name,
                        item_id=item_id,
                        locked=bool(saved_state["sceneItemLocked"]),
                    )

                if "sceneItemIndex" in saved_state:
                    client.set_scene_item_index(
                        scene_name=container_name,
                        item_id=item_id,
                        item_index=int(saved_state["sceneItemIndex"]),
                    )

                client.set_scene_item_enabled(
                    scene_name=container_name,
                    item_id=item_id,
                    enabled=bool(saved_state.get("sceneItemEnabled", True)),
                )
                if "groupItems" not in saved_state:
                    outdated.append(item_name)
                else:
                    missing.extend(
                        f"{item_name} / {source_name}"
                        for source_name in self.restore_group_items(
                            item_name,
                            saved_state.get("groupItems", []),
                        )
                    )

            self.obs_app.refresh_items_state(scene_name)
            preset_name = str(preset.get("name", f"Preset {index + 1}"))
            self.status_var.set(f"Set preset: {preset_name}")

            if missing:
                messagebox.showwarning(
                    "Items Not Found",
                    "These preset items were not found in the current scene:\n\n" + "\n".join(missing),
                    parent=self.parent,
                )
            if outdated:
                messagebox.showwarning(
                    "Preset Needs Re-Save",
                    "This preset was saved before child source settings were supported.\n\n"
                    "Click Add to save a new preset with the current group contents.",
                    parent=self.parent,
                )
        except Exception as error:
            messagebox.showerror("Preset Error", f"Failed to set preset.\n\n{error}", parent=self.parent)



class OBSGroupTogglerApp:
    def __init__(self, parent, connection_parent=None):
        self.parent = parent
        self.connection_parent = connection_parent or parent

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

        connection_main = ttk.Frame(self.connection_parent, padding=12)
        connection_main.pack(fill="x")

        conn_frame = ttk.LabelFrame(connection_main, text="OBS Connection", padding=10)
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

        status_frame = ttk.LabelFrame(connection_main, text="OBS Status", padding=10)
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

    def get_settings(self):
        return {
            "host": self.host_var.get(),
            "port": self.port_var.get(),
            "password": self.password_var.get(),
        }

    def apply_settings(self, payload):
        self.host_var.set(str(payload.get("host", "localhost")))
        self.port_var.set(str(payload.get("port", "4455")))
        self.password_var.set(str(payload.get("password", "")))

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
