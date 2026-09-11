"""A single-selection browser task table with real buttons and wheel scrolling."""

import tkinter as tk
from tkinter import font as tkfont

from .browser_tasks import COMPLETED, ERROR, RUNNING, STOPPING, STATUS_LABELS, task_key


class BrowserTaskTable(tk.Frame):
    HEADERS = ("序号", "浏览器名", "状态", "完成时间", "操作")

    def __init__(self, parent, backend, font_family, on_select, on_start, on_stop, on_complete):
        super().__init__(parent, bg="#16213e")
        self.backend = backend
        self.on_select = on_select
        self.actions = {"start": on_start, "stop": on_stop, "complete": on_complete}
        self.entries = []
        self.rows = {}
        self.selected_id = ""
        self.header_font = tkfont.Font(root=self, family=font_family, size=10, weight="bold")
        self.name_font = tkfont.Font(root=self, family=font_family, size=12)
        self.cell_font = tkfont.Font(root=self, family=font_family, size=10)
        self.small_font = tkfont.Font(root=self, family=font_family, size=9)
        self.header = tk.Frame(self, bg="#0f3460")
        self.header.pack(fill=tk.X)
        for column, text in enumerate(self.HEADERS):
            tk.Label(
                self.header, text=text, font=self.header_font, bg="#0f3460",
                fg="#eaeaea", anchor="w" if column == 1 else "center",
            ).grid(row=0, column=column, sticky="nsew", padx=1, pady=6)
        self.canvas = tk.Canvas(
            self, bg="#16213e", height=300, highlightthickness=0,
            borderwidth=0, yscrollincrement=32, takefocus=True,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.body = tk.Frame(self.canvas, bg="#0f3460")
        self.body_window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Up>", lambda event: self._move_selection(-1))
        self.canvas.bind("<Down>", lambda event: self._move_selection(1))
        self.canvas.bind("<Home>", lambda event: self._move_selection(-len(self.entries)))
        self.canvas.bind("<End>", lambda event: self._move_selection(len(self.entries)))
        self._bind_wheel(self.canvas)
        self._bind_wheel(self.body)
        self._resize_columns()

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._on_wheel)
        widget.bind("<Button-4>", lambda event: self._scroll(-1))
        widget.bind("<Button-5>", lambda event: self._scroll(1))

    def _on_wheel(self, event):
        if event.delta:
            amount = max(1, abs(int(event.delta / 120)))
            return self._scroll(-amount if event.delta > 0 else amount)
        return "break"

    def _scroll(self, amount):
        self.canvas.yview_scroll(amount, "units")
        return "break"

    def _update_scroll_region(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_resize(self, event):
        self.canvas.itemconfigure(self.body_window, width=max(event.width, self.table_width))
        self._update_scroll_region()

    def _resize_columns(self):
        widths = [
            max(self.header_font.measure(self.HEADERS[0]),
                self.cell_font.measure(str(max(1, len(self.entries))))) + 24,
            max([self.header_font.measure(self.HEADERS[1])] +
                [self.name_font.measure(entry["name"]) for entry in self.entries]) + 24,
            max(self.cell_font.measure(label) for label in STATUS_LABELS.values()) + 24,
            self.small_font.measure("8888-88-88 88:88:88") + 24,
            sum(self.small_font.measure(label) + 20 for label in ("开始", "停止", "完成")) + 12,
        ]
        # Include Tk's actual borders/focus rings as well as the text metrics.
        # The header and body must use exactly the same column widths.
        for row in self.rows.values():
            for column, label in enumerate(row["cells"]):
                widths[column] = max(widths[column], label.winfo_reqwidth() + 1)
            widths[4] = max(
                widths[4],
                sum(button.winfo_reqwidth() + 4 for button in row["buttons"].values()),
            )
        for column, width in enumerate(widths):
            self.header.columnconfigure(column, minsize=width)
            self.body.columnconfigure(column, minsize=width)
        self.table_width = sum(widths)
        self.canvas.configure(width=self.table_width)
        self.canvas.itemconfigure(self.body_window, width=self.table_width)

    def set_entries(self, entries, selected_id=""):
        previous_view = self.canvas.yview()[0]
        for widget in self.body.winfo_children():
            widget.destroy()
        self.entries = list(entries)
        self.rows = {}
        for index, entry in enumerate(self.entries):
            entry_id = entry["id"]
            cells = []
            for column, value in enumerate((str(index + 1), entry["name"], "待开始", "—")):
                label = tk.Label(
                    self.body, text=value,
                    font=self.name_font if column == 1 else
                    self.small_font if column == 3 else self.cell_font,
                    anchor="w" if column == 1 else "center", padx=8, pady=5,
                    bg="#16213e", fg="#eaeaea",
                )
                label.grid(row=index, column=column, sticky="nsew", padx=(0, 1), pady=(0, 1))
                label.bind("<Button-1>", lambda event, item=entry_id: self.select(item, notify=True))
                self._bind_wheel(label)
                cells.append(label)
            action_frame = tk.Frame(self.body, bg="#16213e")
            action_frame.grid(row=index, column=4, sticky="nsew", pady=(0, 1))
            buttons = {}
            for action, label, color in (
                ("start", "开始", "#0f3460"),
                ("stop", "停止", "#76334c"),
                ("complete", "完成", "#235345"),
            ):
                button = tk.Button(
                    action_frame, text=label, font=self.small_font,
                    padx=6, pady=2, bg=color, fg="#ffffff",
                    disabledforeground="#8b96a8", activebackground="#00d9ff",
                    activeforeground="#1a1a2e", relief=tk.FLAT,
                    command=lambda item=entry_id, operation=action: self._invoke(operation, item),
                )
                button.pack(side=tk.LEFT, padx=2, pady=3)
                self._bind_wheel(button)
                buttons[action] = button
            self._bind_wheel(action_frame)
            self.rows[entry_id] = {"cells": cells, "frame": action_frame, "buttons": buttons}
        self._resize_columns()
        self.selected_id = ""
        self.select(selected_id)
        self.canvas.yview_moveto(previous_view)
        self.after_idle(self._after_entries)

    def _after_entries(self):
        self._resize_columns()
        self._update_scroll_region()
        self.see(self.selected_id)

    def select(self, entry_id, notify=False):
        if entry_id not in self.rows:
            entry_id = ""
        self.selected_id = entry_id
        for index, entry in enumerate(self.entries):
            color = "#0f3460" if entry["id"] == entry_id else (
                "#16213e" if index % 2 == 0 else "#1a263d"
            )
            row = self.rows[entry["id"]]
            for label in row["cells"]:
                label.configure(bg=color)
            row["frame"].configure(bg=color)
        if notify and entry_id:
            self.canvas.focus_set()
            self.on_select(entry_id)

    def _move_selection(self, offset):
        if self.entries:
            ids = [entry["id"] for entry in self.entries]
            index = ids.index(self.selected_id) if self.selected_id in ids else 0
            entry_id = ids[max(0, min(len(ids) - 1, index + offset))]
            self.select(entry_id, notify=True)
            self.see(entry_id)
        return "break"

    def see(self, entry_id):
        if entry_id not in self.rows or self.canvas.winfo_height() <= 1:
            return
        cell = self.rows[entry_id]["cells"][0]
        top = cell.winfo_y()
        bottom = top + cell.winfo_height()
        view_top = self.canvas.canvasy(0)
        viewport = self.canvas.winfo_height()
        total = max(1, self.body.winfo_reqheight())
        if top < view_top:
            self.canvas.yview_moveto(top / total)
        elif bottom > view_top + viewport:
            self.canvas.yview_moveto(max(0, bottom - viewport) / total)

    def _invoke(self, action, entry_id):
        self.select(entry_id, notify=True)
        self.actions[action](entry_id)

    def render_states(self, registry):
        colors = {RUNNING: "#00d9ff", STOPPING: "#ffaa00",
                  COMPLETED: "#00ff88", ERROR: "#ff758f"}
        for entry_id, row in self.rows.items():
            key = task_key(self.backend, entry_id)
            record = registry.get(key)
            status = record["status"]
            row["cells"][2].configure(text=STATUS_LABELS[status], fg=colors.get(status, "#eaeaea"))
            row["cells"][3].configure(text=record["completed_at"] or "—")
            running = key == registry.active_key and status == RUNNING
            row["buttons"]["start"].configure(state=tk.DISABLED if registry.busy else tk.NORMAL)
            row["buttons"]["stop"].configure(state=tk.NORMAL if running else tk.DISABLED)
            can_complete = status not in (COMPLETED, STOPPING)
            row["buttons"]["complete"].configure(state=tk.NORMAL if can_complete else tk.DISABLED)
        self._resize_columns()
