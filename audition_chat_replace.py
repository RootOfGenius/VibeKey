# -*- coding: utf-8 -*-
import ctypes
import ctypes.wintypes as wt
import base64
import json
import ssl
import shutil
import struct
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from tkinter import messagebox, ttk

try:
    import certifi
except Exception:
    certifi = None


PROCESS_NAME = "Audition.exe"
CHAT_OFFSET = 0x461EB20
BUFFER_SIZE = 512
POLL_SECONDS = 0.03
APP_ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
MAPPING_FILE = APP_ROOT / "audition_emoji_replace.json"
CUSTOM_MAPPING_FILE = APP_ROOT / "audition_emoji_custom.json"
CUSTOM_PACK_KEY = "custom"
STICKER_ROOT = APP_ROOT / "audition_stickers"
METADATA_FILE = APP_ROOT / "app_metadata.json"
SETTINGS_FILE = APP_ROOT / "vibekey_settings.json"

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


def needs_admin_message(exc):
    text = str(exc)
    winerror = getattr(exc, "winerror", None)
    if winerror == 5 or "WinError 5" in text or "Access is denied" in text:
        return "Cần quyền admin. Chuột phải chọn Run as administrator."
    return None


def load_app_metadata():
    defaults = {
        "app_name": "VibeKey",
        "title": "VibeKey",
        "window_title": "VibeKey - Audition Emoji",
        "description": "Tự động chuyển phím tắt thành sticker trong Audition.",
        "author": "Louis Gin",
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


def save_app_metadata(metadata):
    METADATA_FILE.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def https_context():
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def fetch_json(url, timeout=15):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "VibeKey/0.1",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=https_context()) as response:
        data = json.loads(response.read().decode("utf-8"))
    if isinstance(data, dict) and data.get("encoding") == "base64" and "content" in data:
        raw = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(raw)
    return data


def download_file(url, destination, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": "VibeKey/0.1"})
    with urllib.request.urlopen(request, timeout=timeout, context=https_context()) as response:
        with open(destination, "wb") as out:
            shutil.copyfileobj(response, out)


def friendly_update_error(message):
    if "HTTP Error 429" in message:
        return "GitHub đang giới hạn request tạm thời (HTTP 429). Hãy thử lại sau."
    if "CERTIFICATE_VERIFY_FAILED" in message or "certificate verify failed" in message:
        return (
            "Không xác thực được chứng chỉ HTTPS khi kết nối GitHub. "
            "Hãy kiểm tra ngày giờ Windows, mạng/proxy/antivirus, hoặc dùng bản build mới đã đóng kèm chứng chỉ."
        )
    if "<urlopen error" in message:
        return f"Không kết nối được GitHub: {message}"
    return message


def safe_extract_zip(zip_path, target_dir):
    target_dir = Path(target_dir).resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            dest = (target_dir / info.filename).resolve()
            if target_dir not in dest.parents and dest != target_dir:
                raise RuntimeError(f"Duong dan khong an toan trong ZIP: {info.filename}")
        zf.extractall(target_dir)


def archive_root(extract_dir):
    entries = [p for p in Path(extract_dir).iterdir() if p.name not in (".", "..")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return Path(extract_dir)


def copy_allowed_update_files(source_root, app_root, allowed_paths):
    copied = []
    backup_root = app_root / ".update_backup" / time.strftime("%Y%m%d_%H%M%S")
    for allowed in allowed_paths:
        clean = str(allowed).replace("\\", "/").lstrip("/")
        if not clean or clean.startswith(".."):
            continue

        src = source_root / clean
        dst = app_root / clean
        if not src.exists():
            continue

        if dst.exists():
            backup_dst = backup_root / clean
            backup_dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_dir():
                shutil.copytree(dst, backup_dst, dirs_exist_ok=True)
            else:
                shutil.copy2(dst, backup_dst)

        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        copied.append(clean)
    return copied


def update_data_from_github(metadata):
    update_cfg = metadata.get("update", {})
    if not update_cfg.get("enabled"):
        raise RuntimeError("Update dang tat trong app_metadata.json.")

    manifest_url = update_cfg.get("metadata_url", "")
    if not manifest_url:
        raise RuntimeError("Chua cau hinh update.metadata_url.")

    manifest = fetch_json(manifest_url)
    latest_version = str(manifest.get("latest_data_version", ""))
    local_version = str(metadata.get("data_version", ""))
    if not latest_version:
        raise RuntimeError("Manifest thieu latest_data_version.")
    if latest_version == local_version:
        return False, ""

    zip_url = manifest.get("data_zip_url") or update_cfg.get("data_zip_url")
    if not zip_url:
        raise RuntimeError("Manifest thieu data_zip_url.")

    allowed_paths = manifest.get("allowed_paths") or [
        "audition_emoji_replace.json",
        "audition_stickers/",
    ]

    app_root = APP_ROOT
    with tempfile.TemporaryDirectory(prefix="vibekey_update_") as temp_dir:
        temp_dir = Path(temp_dir)
        zip_path = temp_dir / "data_update.zip"
        download_file(zip_url, zip_path)
        extract_dir = temp_dir / "extract"
        extract_dir.mkdir()
        safe_extract_zip(zip_path, extract_dir)
        source_root = archive_root(extract_dir)
        copied = copy_allowed_update_files(source_root, app_root, allowed_paths)

    if not copied:
        raise RuntimeError("ZIP khong co file data hop le de cap nhat.")

    metadata["data_version"] = latest_version
    save_app_metadata(metadata)
    return True, f"Da cap nhat data {local_version} -> {latest_version}."


def check_update_available(metadata):
    update_cfg = metadata.get("update", {})
    if not update_cfg.get("enabled"):
        return False, "Update dang tat."

    manifest_url = update_cfg.get("metadata_url", "")
    if not manifest_url:
        return False, "Chua cau hinh metadata_url."

    manifest = fetch_json(manifest_url)
    latest_version = str(manifest.get("latest_data_version", ""))
    local_version = str(metadata.get("data_version", ""))
    if not latest_version:
        raise RuntimeError("Manifest thieu latest_data_version.")
    return latest_version != local_version, latest_version


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


def load_settings():
    if not SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(settings):
    SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalized_priority_order(packs, saved_order=None):
    saved_order = saved_order or []
    order = [pack_key for pack_key in saved_order if pack_key in packs]
    for pack_key in packs:
        if pack_key not in order:
            order.append(pack_key)
    if CUSTOM_PACK_KEY in order:
        order.remove(CUSTOM_PACK_KEY)
        order.insert(0, CUSTOM_PACK_KEY)
    return order


def normalized_enabled_packs(packs, saved_enabled=None):
    if saved_enabled is None:
        return list(packs.keys())
    enabled = [pack_key for pack_key in saved_enabled if pack_key in packs]
    if CUSTOM_PACK_KEY in packs and CUSTOM_PACK_KEY not in enabled:
        enabled.insert(0, CUSTOM_PACK_KEY)
    return enabled


def build_replace_map(packs, priority_order, enabled_pack_keys=None):
    mapping = {}
    enabled = set(normalized_enabled_packs(packs, enabled_pack_keys))
    for pack_key in reversed(normalized_priority_order(packs, priority_order)):
        if pack_key not in enabled:
            continue
        mapping.update(packs[pack_key]["data"])
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
        self.sticker_set_var = tk.StringVar()
        self.sticker_images = []
        self.sticker_grid = None
        self.priority_listbox = None
        self.custom_key_var = tk.StringVar()
        self.custom_value_var = tk.StringVar()
        self.custom_key_entry = None
        self.custom_value_entry = None
        self.settings = load_settings()
        self.priority_order = []
        self.enabled_pack_keys = []
        self.mapping_mtime = None
        self.custom_mtime = None
        self.running = tk.BooleanVar(value=True)
        self.stop_event = threading.Event()
        self.worker = None
        self.status_var = tk.StringVar(value="")
        self.game_status_var = tk.StringVar(value="Trạng thái: ⠋ Chờ kết nối game")
        self.game_status_label = None
        self.game_connected = False
        self.spinner_index = 0
        self.mapping_info_var = tk.StringVar(value="Chưa nạp JSON.")
        self.version_status_var = tk.StringVar(value=self.version_status_text("Chưa kiểm tra"))
        self.update_button = None
        self.version_label = None
        self.data_update_running = False
        self.replaced_count = 0
        self.replaced_count_var = tk.StringVar(value="Đã thay: 0")

        self.load_mapping(silent=True)
        self.build_style()
        self.build_ui()
        self.load_mapping(silent=True)
        self.after(250, self.auto_start)
        self.after(180, self.animate_game_status)
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
        style.configure("VersionOk.TLabel", background="#101820", foreground="#8cffb0")
        style.configure("VersionWarn.TLabel", background="#101820", foreground="#ffd166")
        style.configure("GameOk.TLabel", background="#101820", foreground="#8cffb0")
        style.configure("GameWait.TLabel", background="#101820", foreground="#ffd166")
        style.configure("TButton", background="#20313d", foreground="#f4f7fb", padding=(12, 8))
        style.configure("Small.TButton", background="#20313d", foreground="#f4f7fb", padding=(8, 4))
        style.map("TButton", background=[("active", "#2b4252")])
        style.configure("TCheckbutton", background="#16232d", foreground="#f4f7fb")
        style.map("TCheckbutton", background=[("active", "#16232d")])
        style.configure("TEntry", fieldbackground="#f7f7f7", foreground="#111111")

    def apply_window_icon(self):
        icon_path = Path(str(self.metadata.get("icon", "")))
        if not icon_path.is_absolute():
            icon_path = APP_ROOT / icon_path
        if icon_path.exists():
            try:
                self.iconphoto(True, tk.PhotoImage(file=str(icon_path)))
            except Exception:
                pass

    def version_status_text(self, suffix):
        return (
            f"Version v{self.metadata.get('version', '0.0.0')} | "
            f"Data {self.metadata.get('data_version', 'unknown')} | {suffix}"
        )

    def set_version_status(self, suffix, ok=False):
        self.version_status_var.set(self.version_status_text(suffix))
        if self.version_label:
            self.version_label.configure(style="VersionOk.TLabel" if ok else "VersionWarn.TLabel")

    def show_update_button(self, show):
        if not self.update_button:
            return
        if show:
            if not self.update_button.winfo_ismapped():
                self.update_button.pack(side="right")
        else:
            if self.update_button.winfo_ismapped():
                self.update_button.pack_forget()

    def build_ui(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x")
        ttk.Label(header, text=self.metadata["title"], font=("Segoe UI", 16, "bold")).pack(side="left", anchor="w")
        self.update_button = ttk.Button(
            header,
            text="Cập nhật",
            style="Small.TButton",
            command=self.start_data_update,
        )
        self.version_label = ttk.Label(
            root,
            textvariable=self.version_status_var,
            style="VersionWarn.TLabel",
        )
        self.version_label.pack(anchor="w", pady=(2, 0))
        ttk.Label(
            root,
            text=self.metadata["description"],
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 2))
        ttk.Label(
            root,
            text=f"Author: {self.metadata.get('author', 'Louis Gin')}",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 4))
        self.game_status_label = ttk.Label(
            root,
            textvariable=self.game_status_var,
            style="GameWait.TLabel",
        )
        self.game_status_label.pack(anchor="w", pady=(0, 12))

        panel = ttk.Frame(root, style="Panel.TFrame", padding=12)
        panel.pack(fill="both", expand=True)

        ttk.Label(panel, text="Thứ tự ưu tiên", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        priority_frame = ttk.Frame(panel, style="Panel.TFrame")
        priority_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.priority_listbox = tk.Listbox(
            priority_frame,
            height=6,
            bg="#101820",
            fg="#f4f7fb",
            selectbackground="#2b4252",
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground="#2f4352",
            activestyle="none",
            exportselection=False,
        )
        self.priority_listbox.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=(0, 8))
        ttk.Button(priority_frame, text="Lên", style="Small.TButton", command=lambda: self.move_priority(-1)).grid(
            row=0, column=1, sticky="ew", pady=(0, 4)
        )
        ttk.Button(priority_frame, text="Xuống", style="Small.TButton", command=lambda: self.move_priority(1)).grid(
            row=1, column=1, sticky="ew", pady=(0, 4)
        )
        ttk.Button(priority_frame, text="Bật/tắt", style="Small.TButton", command=self.toggle_selected_pack).grid(
            row=2, column=1, sticky="ew"
        )
        priority_frame.columnconfigure(0, weight=1)
        ttk.Label(panel, textvariable=self.mapping_info_var, style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=4
        )
        custom = ttk.Frame(panel, style="Panel.TFrame")
        custom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(custom, text="Key", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.custom_key_entry = ttk.Entry(custom, width=14)
        self.custom_key_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(custom, text="Giá trị", style="Panel.TLabel").grid(row=0, column=1, sticky="w")
        self.custom_value_entry = ttk.Entry(custom, width=18)
        self.custom_value_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(custom, text="Thêm custom", command=self.add_custom_mapping).grid(
            row=1, column=2, sticky="ew"
        )
        custom.columnconfigure(0, weight=1)
        custom.columnconfigure(1, weight=1)

        ttk.Label(panel, textvariable=self.status_var, style="Panel.TLabel", wraplength=380).grid(
            row=4, column=0, sticky="w", pady=(12, 4)
        )
        panel.columnconfigure(0, weight=1)
        self.setup_entry_placeholder(self.custom_key_entry, "Ví dụ: ;haha")
        self.setup_entry_placeholder(self.custom_value_entry, "Ví dụ: &^_^&")

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
            self.packs = load_pack_file()
            self.packs[CUSTOM_PACK_KEY] = load_custom_mapping()
            self.mapping_mtime = MAPPING_FILE.stat().st_mtime
            self.custom_mtime = CUSTOM_MAPPING_FILE.stat().st_mtime

            self.pack_labels = {
                pack_key: f"{pack['label']} ({pack_key})"
                for pack_key, pack in self.packs.items()
            }
            self.priority_order = normalized_priority_order(
                self.packs,
                self.settings.get("priority_order", self.priority_order),
            )
            self.enabled_pack_keys = normalized_enabled_packs(
                self.packs,
                self.settings.get("enabled_pack_keys", self.enabled_pack_keys or None),
            )
            self.replace_map = build_replace_map(self.packs, self.priority_order, self.enabled_pack_keys)

            if hasattr(self, "priority_listbox") and self.priority_listbox:
                self.refresh_priority_listbox()
            if hasattr(self, "sticker_combo"):
                values = [self.pack_labels[key] for key in self.packs]
                current_sticker = self.sticker_set_var.get()
                self.sticker_combo["values"] = values
                if current_sticker not in values:
                    first_pack = self.priority_order[0] if self.priority_order else next(iter(self.packs))
                    self.sticker_set_var.set(self.pack_labels[first_pack])
                self.refresh_sticker_showcase()

            if hasattr(self, "mapping_info_var"):
                self.update_mapping_info()
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

    def refresh_priority_listbox(self):
        if not self.priority_listbox:
            return
        selected = self.priority_listbox.curselection()
        selected_index = selected[0] if selected else 0
        self.priority_listbox.delete(0, "end")
        for index, pack_key in enumerate(self.priority_order, start=1):
            marker = "✓" if pack_key in self.enabled_pack_keys else "○"
            self.priority_listbox.insert("end", f"{marker} {index}. {self.pack_labels[pack_key]}")
        if self.priority_order:
            selected_index = min(selected_index, len(self.priority_order) - 1)
            self.priority_listbox.selection_set(selected_index)

    def update_mapping_info(self):
        enabled_order = [pack_key for pack_key in self.priority_order if pack_key in self.enabled_pack_keys]
        top_key = enabled_order[0] if enabled_order else None
        top_label = self.packs[top_key]["label"] if top_key in self.packs else "--"
        self.mapping_info_var.set(
            f"{len(self.replace_map)} mẫu / {len(self.enabled_pack_keys)}/{len(self.packs)} gói bật. Ưu tiên cao nhất: {top_label}"
        )

    def save_user_settings(self):
        self.settings["priority_order"] = self.priority_order
        self.settings["enabled_pack_keys"] = self.enabled_pack_keys
        save_settings(self.settings)

    def move_priority(self, direction):
        if not self.priority_listbox or not self.priority_order:
            return
        selected = self.priority_listbox.curselection()
        if not selected:
            return
        index = selected[0]
        new_index = index + direction
        if new_index < 0 or new_index >= len(self.priority_order):
            return
        self.priority_order[index], self.priority_order[new_index] = (
            self.priority_order[new_index],
            self.priority_order[index],
        )
        self.save_user_settings()
        self.replace_map = build_replace_map(self.packs, self.priority_order, self.enabled_pack_keys)
        self.refresh_priority_listbox()
        self.priority_listbox.selection_clear(0, "end")
        self.priority_listbox.selection_set(new_index)
        self.priority_listbox.see(new_index)
        self.update_mapping_info()
        self.status_var.set("Đã đổi thứ tự ưu tiên.")

    def toggle_selected_pack(self):
        if not self.priority_listbox or not self.priority_order:
            return
        selected = self.priority_listbox.curselection()
        if not selected:
            return
        index = selected[0]
        pack_key = self.priority_order[index]
        if pack_key == CUSTOM_PACK_KEY:
            self.status_var.set("Custom luôn được bật để ưu tiên mapping của bạn.")
            return
        if pack_key in self.enabled_pack_keys:
            if len(self.enabled_pack_keys) <= 1:
                messagebox.showwarning("Không thể tắt", "Cần bật ít nhất 1 gói emoji.")
                return
            self.enabled_pack_keys.remove(pack_key)
            self.status_var.set(f"Đã tắt: {self.packs[pack_key]['label']}")
        else:
            self.enabled_pack_keys.append(pack_key)
            self.status_var.set(f"Đã bật: {self.packs[pack_key]['label']}")
        self.save_user_settings()
        self.replace_map = build_replace_map(self.packs, self.priority_order, self.enabled_pack_keys)
        self.refresh_priority_listbox()
        self.priority_listbox.selection_clear(0, "end")
        self.priority_listbox.selection_set(index)
        self.update_mapping_info()

    def on_sticker_set_selected(self, _event=None):
        self.refresh_sticker_showcase()

    def selected_sticker_pack_key(self):
        selected_label = self.sticker_set_var.get()
        for pack_key, label in self.pack_labels.items():
            if label == selected_label:
                return pack_key
        return self.priority_order[0] if self.priority_order else None

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

    def setup_entry_placeholder(self, entry, placeholder):
        entry.placeholder = placeholder
        entry.is_placeholder = True
        entry.insert(0, placeholder)
        entry.configure(foreground="#777777")

        def on_focus_in(_event):
            if getattr(entry, "is_placeholder", False):
                entry.delete(0, "end")
                entry.configure(foreground="#111111")
                entry.is_placeholder = False

        def on_focus_out(_event):
            if not entry.get().strip():
                entry.insert(0, placeholder)
                entry.configure(foreground="#777777")
                entry.is_placeholder = True

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

    def entry_value(self, entry):
        if not entry or getattr(entry, "is_placeholder", False):
            return ""
        return entry.get().strip()

    def clear_entry_placeholder(self, entry):
        if not entry:
            return
        entry.delete(0, "end")
        entry.insert(0, entry.placeholder)
        entry.configure(foreground="#777777")
        entry.is_placeholder = True

    def add_custom_mapping(self):
        source = self.entry_value(self.custom_key_entry)
        target = self.entry_value(self.custom_value_entry)
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
            if CUSTOM_PACK_KEY in self.priority_order:
                self.priority_order.remove(CUSTOM_PACK_KEY)
            self.priority_order.insert(0, CUSTOM_PACK_KEY)
            if CUSTOM_PACK_KEY not in self.enabled_pack_keys:
                self.enabled_pack_keys.insert(0, CUSTOM_PACK_KEY)
            self.save_user_settings()
            self.clear_entry_placeholder(self.custom_key_entry)
            self.clear_entry_placeholder(self.custom_value_entry)
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

    def start_data_update(self):
        self.status_var.set("Đang kiểm tra cập nhật data...")
        threading.Thread(target=self.update_data_worker, daemon=True).start()

    def update_data_worker(self):
        try:
            changed, message = update_data_from_github(self.metadata)
            self.metadata = load_app_metadata()
            self.load_mapping(silent=True)
            self.refresh_sticker_showcase()
            self.status_var.set(message)
            if changed:
                messagebox.showinfo("Cập nhật data", message)
        except Exception as exc:
            self.status_var.set(f"Lỗi cập nhật data: {exc}")
            messagebox.showerror("Lỗi cập nhật data", str(exc))

    def start_update_check(self):
        self.set_version_status("Đang kiểm tra", ok=False)
        self.show_update_button(False)
        threading.Thread(target=self.update_check_worker, daemon=True).start()

    def update_check_worker(self):
        try:
            has_update, latest_version = check_update_available(self.metadata)
            self.after(0, lambda: self.finish_update_check(True, has_update, latest_version))
        except Exception as exc:
            self.after(0, lambda exc=exc: self.finish_update_check(False, False, str(exc)))

    def finish_update_check(self, success, has_update, detail):
        if success and has_update:
            self.set_version_status(f"Có data mới {detail}", ok=False)
            self.show_update_button(True)
        elif success:
            self.set_version_status("Mới nhất", ok=True)
            self.show_update_button(False)
        else:
            friendly = friendly_update_error(detail)
            self.set_version_status(f"Chưa kiểm tra được ({friendly})", ok=False)
            self.show_update_button(True)

    def start_data_update(self):
        if self.data_update_running:
            return
        self.data_update_running = True
        if self.update_button:
            self.update_button.configure(state="disabled", text="...")
        self.set_version_status("Đang kiểm tra", ok=False)
        self.status_var.set("Đang kiểm tra cập nhật data...")
        threading.Thread(target=self.update_data_worker, daemon=True).start()

    def update_data_worker(self):
        try:
            changed, message = update_data_from_github(self.metadata)
            self.after(0, lambda: self.finish_data_update(True, changed, message))
        except Exception as exc:
            self.after(0, lambda exc=exc: self.finish_data_update(False, False, str(exc)))

    def finish_data_update(self, success, changed, message):
        self.data_update_running = False
        if self.update_button:
            self.update_button.configure(state="normal", text="Cập nhật")
        if success:
            self.metadata = load_app_metadata()
            self.load_mapping(silent=True)
            self.refresh_sticker_showcase()
            self.set_version_status("Mới nhất", ok=True)
            self.show_update_button(False)
            if changed:
                self.status_var.set(f"{message} Đã reload data.")
        else:
            friendly = friendly_update_error(message)
            self.set_version_status("Chưa kiểm tra được", ok=False)
            self.show_update_button(True)
            self.status_var.set(f"Lỗi cập nhật data: {friendly}")

    def auto_start(self):
        self.attach(show_error=False)
        self.toggle_worker()
        self.start_update_check()

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

    def attach(self, show_error=True):
        try:
            self.mem.attach()
            self.status_var.set(
                f"Đã kết nối PID {self.mem.pid}, địa chỉ chat 0x{self.mem.chat_address:X}."
            )
        except Exception as exc:
            admin_msg = needs_admin_message(exc)
            self.status_var.set(admin_msg or "Lỗi kết nối.")
            if show_error:
                messagebox.showerror("Lỗi kết nối", admin_msg or str(exc))

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
                except Exception as exc:
                    self.mem.close()
                    admin_msg = needs_admin_message(exc)
                    self.status_var.set(
                        admin_msg
                        or "Đang chờ Audition. Nếu không kết nối được: chuột phải chọn Run as administrator."
                    )
            time.sleep(POLL_SECONDS)

    def set_game_waiting(self, message=None):
        self.game_connected = False
        if self.game_status_label:
            self.game_status_label.configure(style="GameWait.TLabel")
        if message:
            self.game_status_var.set(f"Trạng thái: {message}")

    def set_game_connected(self):
        self.game_connected = True
        if self.game_status_label:
            self.game_status_label.configure(style="GameOk.TLabel")
        self.game_status_var.set("Trạng thái: ✓ Đã kết nối")

    def animate_game_status(self):
        if not self.game_connected:
            frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
            frame = frames[self.spinner_index % len(frames)]
            self.spinner_index += 1
            current = self.game_status_var.get()
            if "Run as administrator" in current:
                self.game_status_var.set(f"Trạng thái: {frame} Cần quyền admin. Chuột phải chọn Run as administrator.")
            else:
                self.game_status_var.set(f"Trạng thái: {frame} Chờ kết nối game")
        self.after(180, self.animate_game_status)

    def attach(self, show_error=True):
        try:
            self.mem.attach()
            self.set_game_connected()
        except Exception as exc:
            admin_msg = needs_admin_message(exc)
            if admin_msg:
                self.set_game_waiting(admin_msg)
            else:
                self.set_game_waiting()
            if show_error:
                messagebox.showerror("Lỗi kết nối", admin_msg or str(exc))

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
                    if not self.game_connected:
                        self.set_game_connected()
                except Exception as exc:
                    self.mem.close()
                    admin_msg = needs_admin_message(exc)
                    if admin_msg:
                        self.set_game_waiting(admin_msg)
                    else:
                        self.set_game_waiting()
            time.sleep(POLL_SECONDS)

    def toggle_worker(self):
        if self.running.get():
            self.load_mapping(silent=True)
            if not self.worker or not self.worker.is_alive():
                self.worker = threading.Thread(target=self.worker_loop, daemon=True)
                self.worker.start()

    def replace_once(self):
        try:
            self.ensure_attached()
            text = self.mem.read_chat()
            new_text, hits = apply_replace_map(text, self.replace_map)
            if hits:
                self.mem.write_chat(new_text)
                self.replaced_count += sum(hit[2] for hit in hits)
                self.status_var.set(f"Đã thay {len(hits)} loại key.")
        except Exception as exc:
            self.status_var.set("Lỗi thay thế.")
            messagebox.showerror("Lỗi thay thế", str(exc))

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
                    if not self.game_connected:
                        self.set_game_connected()
                except Exception as exc:
                    self.mem.close()
                    admin_msg = needs_admin_message(exc)
                    if admin_msg:
                        self.set_game_waiting(admin_msg)
                    else:
                        self.set_game_waiting()
            time.sleep(POLL_SECONDS)

    def on_close(self):
        self.stop_event.set()
        self.mem.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
