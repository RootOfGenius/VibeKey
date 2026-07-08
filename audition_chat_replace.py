# -*- coding: utf-8 -*-
import ctypes
import ctypes.wintypes as wt
import json
import struct
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


PROCESS_NAME = "Audition.exe"
CHAT_OFFSET = 0x461EB20
BUFFER_SIZE = 512
POLL_SECONDS = 0.03
MAPPING_FILE = Path(__file__).with_name("audition_emoji_replace.json")
CUSTOM_MAPPING_FILE = Path(__file__).with_name("audition_emoji_custom.json")
CUSTOM_PACK_KEY = "custom"
STICKER_ROOT = Path(__file__).with_name("audition_stickers")
METADATA_FILE = Path(__file__).with_name("app_metadata.json")

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
TH32CS_SNAPPROCESS = 0x00000002

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wt.ULONG)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("Reserved3", ctypes.c_void_p),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.ReadProcessMemory.argtypes = [
    wt.HANDLE,
    wt.LPCVOID,
    wt.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.WriteProcessMemory.argtypes = [
    wt.HANDLE,
    wt.LPVOID,
    wt.LPCVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.IsWow64Process.argtypes = [wt.HANDLE, ctypes.POINTER(wt.BOOL)]
ntdll.NtQueryInformationProcess.argtypes = [
    wt.HANDLE,
    wt.ULONG,
    wt.LPVOID,
    wt.ULONG,
    ctypes.POINTER(wt.ULONG),
]


def win_error():
    return ctypes.WinError(ctypes.get_last_error())


def find_pid(process_name):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == wt.HANDLE(-1).value:
        raise win_error()
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == process_name.lower():
                return entry.th32ProcessID
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return None


def c_string(data):
    end = data.find(b"\x00")
    return data if end < 0 else data[:end]


def load_app_metadata():
    defaults = {
        "app_name": "VibeKey",
        "title": "VibeKey",
        "window_title": "VibeKey - Audition Emoji",
        "description": "Tự động chuyển phím tắt thành sticker trong Audition.",
        "version": "0.1.0",
        "icon": "assets/app_icon.png",
        "update": {
            "enabled": False,
            "metadata_url": "",
            "zip_url": "",
            "channel": "stable",
        },
    }
    if not METADATA_FILE.exists():
        METADATA_FILE.write_text(
            json.dumps(defaults, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return defaults

    try:
        data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return defaults

    if not isinstance(data, dict):
        return defaults

    merged = defaults | data
    update = defaults["update"] | data.get("update", {}) if isinstance(data.get("update"), dict) else defaults["update"]
    merged["update"] = update
    return merged


def load_pack_file():
    if not MAPPING_FILE.exists():
        default_data = {
            "emoji_basic": {
                "label": "Emoji co ban",
                "data": {";haha": "&^_^&"},
            }
        }
        MAPPING_FILE.write_text(
            json.dumps(default_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    data = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON goc phai la object cac pack.")

    packs = {}
    for pack_key, pack in data.items():
        if not isinstance(pack, dict):
            continue
        label = pack.get("label", pack_key)
        mapping = pack.get("data", {})
        if not isinstance(mapping, dict):
            continue
        clean_mapping = {
            str(key): str(value)
            for key, value in mapping.items()
            if isinstance(value, str) and str(key)
        }
        packs[str(pack_key)] = {
            "label": str(label),
            "data": clean_mapping,
        }

    if not packs:
        raise ValueError("Khong co pack hop le. Moi pack can co label va data.")
    return packs


def load_custom_mapping():
    if not CUSTOM_MAPPING_FILE.exists():
        CUSTOM_MAPPING_FILE.write_text(
            json.dumps({"label": "Tùy chỉnh", "data": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    data = json.loads(CUSTOM_MAPPING_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON custom phai la object.")

    label = str(data.get("label", "Tùy chỉnh"))
    mapping = data.get("data", {})
    if not isinstance(mapping, dict):
        mapping = {}

    clean_mapping = {
        str(key): str(value)
        for key, value in mapping.items()
        if isinstance(value, str) and str(key)
    }
    return {"label": label, "data": clean_mapping}


def save_custom_mapping(custom_pack):
    CUSTOM_MAPPING_FILE.write_text(
        json.dumps(custom_pack, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_replace_map(packs, preferred_pack_key):
    mapping = {}
    for pack_key, pack in packs.items():
        if pack_key != preferred_pack_key:
            mapping.update(pack["data"])
    if preferred_pack_key in packs:
        mapping.update(packs[preferred_pack_key]["data"])
    return dict(sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True))


def apply_replace_map(text, mapping):
    new_text = text
    hits = []
    for source, target in mapping.items():
        if source and source in new_text:
            count = new_text.count(source)
            new_text = new_text.replace(source, target)
            hits.append((source, target, count))
    return new_text, hits


class AuditionMemory:
    def __init__(self):
        self.pid = None
        self.handle = None
        self.image_base = None
        self.chat_address = None

    def attach(self):
        self.close()
        pid = find_pid(PROCESS_NAME)
        if not pid:
            raise RuntimeError(f"Khong tim thay {PROCESS_NAME}")

        rights = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        handle = kernel32.OpenProcess(rights, False, pid)
        if not handle:
            raise win_error()

        self.pid = pid
        self.handle = handle
        self.image_base = self.get_image_base()
        self.chat_address = self.image_base + CHAT_OFFSET

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
        self.pid = None
        self.handle = None
        self.image_base = None
        self.chat_address = None

    def read(self, address, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        ok = kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buf,
            size,
            ctypes.byref(got),
        )
        if not ok:
            raise win_error()
        return buf.raw[: got.value]

    def write(self, address, data):
        buf = ctypes.create_string_buffer(data)
        written = ctypes.c_size_t()
        ok = kernel32.WriteProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buf,
            len(data),
            ctypes.byref(written),
        )
        if not ok:
            raise win_error()
        return written.value == len(data)

    def get_image_base(self):
        pbi = PROCESS_BASIC_INFORMATION()
        returned = wt.ULONG()
        status = ntdll.NtQueryInformationProcess(
            self.handle,
            0,
            ctypes.byref(pbi),
            ctypes.sizeof(pbi),
            ctypes.byref(returned),
        )
        if status != 0:
            raise OSError(f"NtQueryInformationProcess failed: 0x{status & 0xFFFFFFFF:X}")

        wow = wt.BOOL(False)
        if kernel32.IsWow64Process(self.handle, ctypes.byref(wow)) and wow.value:
            wow_peb = ctypes.c_void_p()
            status = ntdll.NtQueryInformationProcess(
                self.handle,
                26,
                ctypes.byref(wow_peb),
                ctypes.sizeof(wow_peb),
                ctypes.byref(returned),
            )
            if status == 0 and wow_peb.value:
                return struct.unpack("<I", self.read(wow_peb.value + 0x08, 4))[0]

        if pbi.PebBaseAddress:
            return struct.unpack("<Q", self.read(pbi.PebBaseAddress + 0x10, 8))[0]

        raise RuntimeError("Khong lay duoc image base.")

    def read_chat(self):
        data = self.read(self.chat_address, BUFFER_SIZE)
        return c_string(data).decode("cp1258", errors="replace")

    def write_chat(self, text):
        raw = text.encode("cp1258", errors="replace")
        if len(raw) >= BUFFER_SIZE:
            raise ValueError("Text qua dai so voi buffer chat.")
        payload = raw + b"\x00"
        return self.write(self.chat_address, payload)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.metadata = load_app_metadata()
        self.title(self.metadata["window_title"])
        self.geometry("560x720")
        self.minsize(520, 600)
        self.configure(bg="#101820")
        self.apply_window_icon()

        self.mem = AuditionMemory()
        self.packs = {}
        self.replace_map = {}
        self.pack_labels = {}
        self.pack_select_var = tk.StringVar()
        self.sticker_set_var = tk.StringVar()
        self.sticker_images = []
        self.sticker_grid = None
        self.custom_key_var = tk.StringVar()
        self.custom_value_var = tk.StringVar()
        self.selected_pack_key = None
        self.mapping_mtime = None
        self.custom_mtime = None
        self.running = tk.BooleanVar(value=True)
        self.stop_event = threading.Event()
        self.worker = None
        self.status_var = tk.StringVar(value="Đang khởi động...")
        self.mapping_info_var = tk.StringVar(value="Chưa nạp JSON.")
        self.replaced_count = 0
        self.replaced_count_var = tk.StringVar(value="Đã thay: 0")

        self.load_mapping(silent=True)
        self.build_style()
        self.build_ui()
        self.load_mapping(silent=True)
        self.after(250, self.auto_start)
        self.after(800, self.watch_mapping_file)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background="#101820")
        style.configure("Panel.TFrame", background="#16232d")
        style.configure("TLabel", background="#101820", foreground="#f4f7fb")
        style.configure("Panel.TLabel", background="#16232d", foreground="#f4f7fb")
        style.configure("Muted.TLabel", background="#101820", foreground="#a9bac8")
        style.configure("TButton", background="#20313d", foreground="#f4f7fb", padding=(12, 8))
        style.map("TButton", background=[("active", "#2b4252")])
        style.configure("TCheckbutton", background="#16232d", foreground="#f4f7fb")
        style.map("TCheckbutton", background=[("active", "#16232d")])
        style.configure("TEntry", fieldbackground="#f7f7f7", foreground="#111111")

    def apply_window_icon(self):
        icon_path = Path(str(self.metadata.get("icon", "")))
        if not icon_path.is_absolute():
            icon_path = Path(__file__).parent / icon_path
        if icon_path.exists():
            try:
                self.iconphoto(True, tk.PhotoImage(file=str(icon_path)))
            except Exception:
                pass

    def build_ui(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        header = f"{self.metadata['title']} v{self.metadata['version']}"
        ttk.Label(root, text=header, font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text=self.metadata["description"],
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        panel = ttk.Frame(root, style="Panel.TFrame", padding=12)
        panel.pack(fill="both", expand=True)

        ttk.Label(panel, text="Gói ưu tiên", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.pack_combo = ttk.Combobox(
            panel,
            textvariable=self.pack_select_var,
            state="readonly",
            width=28,
        )
        self.pack_combo.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.pack_combo.bind("<<ComboboxSelected>>", self.on_pack_selected)
        ttk.Label(panel, textvariable=self.mapping_info_var, style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=4
        )
        custom = ttk.Frame(panel, style="Panel.TFrame")
        custom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(custom, text="Key", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(custom, textvariable=self.custom_key_var, width=14).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(custom, text="Giá trị", style="Panel.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(custom, textvariable=self.custom_value_var, width=18).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(custom, text="Thêm custom", command=self.add_custom_mapping).grid(
            row=1, column=2, sticky="ew"
        )
        custom.columnconfigure(0, weight=1)
        custom.columnconfigure(1, weight=1)

        ttk.Label(panel, textvariable=self.status_var, style="Panel.TLabel", wraplength=380).grid(
            row=4, column=0, sticky="w", pady=(12, 4)
        )
        ttk.Label(panel, textvariable=self.replaced_count_var, style="Panel.TLabel").grid(
            row=5, column=0, sticky="w", pady=(10, 0)
        )
        panel.columnconfigure(0, weight=1)

        showcase = ttk.Frame(root, style="Panel.TFrame", padding=12)
        showcase.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(showcase, text="Bộ sticker", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.sticker_combo = ttk.Combobox(
            showcase,
            textvariable=self.sticker_set_var,
            state="readonly",
            width=28,
        )
        self.sticker_combo.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        self.sticker_combo.bind("<<ComboboxSelected>>", self.on_sticker_set_selected)
        sticker_area = ttk.Frame(showcase, style="Panel.TFrame")
        sticker_area.grid(row=2, column=0, sticky="nsew")
        self.sticker_canvas = tk.Canvas(
            sticker_area,
            bg="#16232d",
            highlightthickness=0,
            borderwidth=0,
            height=380,
        )
        sticker_scroll = ttk.Scrollbar(sticker_area, orient="vertical", command=self.sticker_canvas.yview)
        self.sticker_canvas.configure(yscrollcommand=sticker_scroll.set)
        self.sticker_canvas.pack(side="left", fill="both", expand=True)
        sticker_scroll.pack(side="right", fill="y")
        self.sticker_grid = ttk.Frame(self.sticker_canvas, style="Panel.TFrame")
        self.sticker_window = self.sticker_canvas.create_window((0, 0), window=self.sticker_grid, anchor="nw")
        self.sticker_grid.bind(
            "<Configure>",
            lambda _event: self.sticker_canvas.configure(scrollregion=self.sticker_canvas.bbox("all")),
        )
        self.sticker_canvas.bind(
            "<Configure>",
            lambda event: self.sticker_canvas.itemconfigure(self.sticker_window, width=event.width),
        )
        self.sticker_canvas.bind(
            "<MouseWheel>",
            lambda event: self.sticker_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"),
        )
        showcase.columnconfigure(0, weight=1)
        showcase.rowconfigure(2, weight=1)

    def load_mapping(self, silent=False):
        try:
            previous_key = self.selected_pack_key
            self.packs = load_pack_file()
            self.packs[CUSTOM_PACK_KEY] = load_custom_mapping()
            self.mapping_mtime = MAPPING_FILE.stat().st_mtime
            self.custom_mtime = CUSTOM_MAPPING_FILE.stat().st_mtime

            if previous_key not in self.packs:
                previous_key = next(iter(self.packs))
            self.selected_pack_key = previous_key

            self.pack_labels = {
                pack_key: f"{pack['label']} ({pack_key})"
                for pack_key, pack in self.packs.items()
            }
            self.replace_map = build_replace_map(self.packs, self.selected_pack_key)

            if hasattr(self, "pack_combo"):
                values = [self.pack_labels[key] for key in self.packs]
                self.pack_combo["values"] = values
                self.pack_select_var.set(self.pack_labels[self.selected_pack_key])
            if hasattr(self, "sticker_combo"):
                values = [self.pack_labels[key] for key in self.packs]
                current_sticker = self.sticker_set_var.get()
                self.sticker_combo["values"] = values
                if current_sticker not in values:
                    self.sticker_set_var.set(self.pack_labels[self.selected_pack_key])
                self.refresh_sticker_showcase()

            if hasattr(self, "mapping_info_var"):
                selected_label = self.packs[self.selected_pack_key]["label"]
                self.mapping_info_var.set(
                    f"{len(self.replace_map)} mẫu / {len(self.packs)} gói. Ưu tiên: {selected_label}"
                )
            if not silent:
                self.status_var.set("Đã tự nạp lại JSON.")
        except Exception as exc:
            old_map = self.replace_map
            self.replace_map = {}
            if hasattr(self, "mapping_info_var"):
                self.mapping_info_var.set(f"Lỗi JSON: {exc}")
            self.replace_map = old_map
            if not silent:
                messagebox.showerror("Lỗi JSON", str(exc))

    def on_pack_selected(self, _event=None):
        selected_label = self.pack_select_var.get()
        for pack_key, label in self.pack_labels.items():
            if label == selected_label:
                self.selected_pack_key = pack_key
                self.replace_map = build_replace_map(self.packs, self.selected_pack_key)
                selected_name = self.packs[pack_key]["label"]
                self.mapping_info_var.set(
                    f"{len(self.replace_map)} mẫu / {len(self.packs)} gói. Ưu tiên: {selected_name}"
                )
                self.status_var.set("Đã đổi gói ưu tiên.")
                return

    def on_sticker_set_selected(self, _event=None):
        self.refresh_sticker_showcase()

    def selected_sticker_pack_key(self):
        selected_label = self.sticker_set_var.get()
        for pack_key, label in self.pack_labels.items():
            if label == selected_label:
                return pack_key
        return self.selected_pack_key

    def refresh_sticker_showcase(self):
        if not self.sticker_grid:
            return
        for child in self.sticker_grid.winfo_children():
            child.destroy()
        self.sticker_images = []

        pack_key = self.selected_sticker_pack_key()
        if not pack_key or pack_key not in self.packs:
            return

        keys = list(self.packs[pack_key]["data"].keys())
        icon_dir = STICKER_ROOT / pack_key
        columns = 8

        for index, key in enumerate(keys):
            row = index // columns
            col = index % columns
            cell = ttk.Frame(self.sticker_grid, style="Panel.TFrame", padding=(2, 2))
            cell.grid(row=row, column=col, padx=3, pady=4, sticky="n")

            icon_path = icon_dir / f"{index + 1:02d}.png"
            if icon_path.exists():
                try:
                    image = tk.PhotoImage(file=str(icon_path))
                    self.sticker_images.append(image)
                    ttk.Label(cell, image=image, style="Panel.TLabel").pack()
                except Exception:
                    ttk.Label(cell, text="?", style="Panel.TLabel", width=4).pack()
            else:
                ttk.Label(cell, text="□", style="Panel.TLabel", width=4).pack()

            ttk.Label(cell, text=key, style="Panel.TLabel", font=("Segoe UI", 8)).pack()

        for col in range(columns):
            self.sticker_grid.columnconfigure(col, weight=1)

    def add_custom_mapping(self):
        source = self.custom_key_var.get().strip()
        target = self.custom_value_var.get().strip()
        if not source:
            messagebox.showwarning("Thiếu key", "Bạn cần nhập key, ví dụ ;win.")
            return
        if not target:
            messagebox.showwarning("Thiếu giá trị", "Bạn cần nhập giá trị thay thế.")
            return

        try:
            custom_pack = load_custom_mapping()
            if source in custom_pack["data"]:
                messagebox.showwarning(
                    "Trùng key",
                    f"Key {source} đã tồn tại trong custom. Custom không được có 2 key giống nhau.",
                )
                return

            custom_pack["data"][source] = target
            save_custom_mapping(custom_pack)
            self.selected_pack_key = CUSTOM_PACK_KEY
            self.custom_key_var.set("")
            self.custom_value_var.set("")
            self.load_mapping(silent=False)
            self.status_var.set(f"Đã thêm custom: {source} -> {target}")
        except Exception as exc:
            messagebox.showerror("Lỗi custom", str(exc))

    def watch_mapping_file(self):
        try:
            current_mtime = MAPPING_FILE.stat().st_mtime
            if self.mapping_mtime is None or current_mtime != self.mapping_mtime:
                self.load_mapping(silent=False)
        except Exception as exc:
            self.mapping_info_var.set(f"Không đọc được JSON: {exc}")
        self.after(800, self.watch_mapping_file)

    def watch_mapping_file(self):
        try:
            current_mtime = MAPPING_FILE.stat().st_mtime
            current_custom_mtime = CUSTOM_MAPPING_FILE.stat().st_mtime if CUSTOM_MAPPING_FILE.exists() else None
            if (
                self.mapping_mtime is None
                or current_mtime != self.mapping_mtime
                or current_custom_mtime != self.custom_mtime
            ):
                self.load_mapping(silent=False)
        except Exception as exc:
            self.mapping_info_var.set(f"Không đọc được JSON: {exc}")
        self.after(800, self.watch_mapping_file)

    def auto_start(self):
        self.attach(show_error=False)
        self.toggle_worker()

    def attach(self, show_error=True):
        try:
            self.mem.attach()
            self.status_var.set(
                f"Đã kết nối PID {self.mem.pid}, địa chỉ chat 0x{self.mem.chat_address:X}."
            )
        except Exception as exc:
            self.status_var.set("Lỗi kết nối.")
            if show_error:
                messagebox.showerror("Lỗi kết nối", str(exc))

    def ensure_attached(self):
        if not self.mem.handle:
            self.attach(show_error=False)
        if not self.mem.handle:
            raise RuntimeError("Chưa kết nối Audition.")

    def read_once(self, show_error=True):
        try:
            self.ensure_attached()
            return self.mem.read_chat()
        except Exception as exc:
            self.status_var.set("Lỗi đọc.")
            if show_error:
                messagebox.showerror("Lỗi đọc", str(exc))
            return ""

    def replace_once(self):
        try:
            self.ensure_attached()
            text = self.mem.read_chat()
            new_text, hits = apply_replace_map(text, self.replace_map)
            if hits:
                self.mem.write_chat(new_text)
                self.replaced_count += sum(hit[2] for hit in hits)
                self.replaced_count_var.set(f"Đã thay: {self.replaced_count}")
                self.status_var.set(f"Đã thay {len(hits)} loại key.")
        except Exception as exc:
            self.status_var.set("Lỗi thay thế.")
            messagebox.showerror("Lỗi thay thế", str(exc))

    def toggle_worker(self):
        if self.running.get():
            self.load_mapping(silent=True)
            if not self.worker or not self.worker.is_alive():
                self.worker = threading.Thread(target=self.worker_loop, daemon=True)
                self.worker.start()
            self.status_var.set("Đang tự động thay thế.")
        else:
            self.status_var.set("Đã tắt tự động thay thế.")

    def worker_loop(self):
        while not self.stop_event.is_set():
            if self.running.get():
                try:
                    self.ensure_attached()
                    text = self.mem.read_chat()
                    new_text, hits = apply_replace_map(text, self.replace_map)
                    if hits and new_text != text:
                        self.mem.write_chat(new_text)
                        self.replaced_count += sum(hit[2] for hit in hits)
                        self.replaced_count_var.set(f"Đã thay: {self.replaced_count}")
                except Exception:
                    self.mem.close()
                    self.status_var.set("Đang chờ Audition hoặc quyền admin...")
            time.sleep(POLL_SECONDS)

    def on_close(self):
        self.stop_event.set()
        self.mem.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
