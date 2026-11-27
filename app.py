

import argparse
import asyncio
import atexit
import base64
import ctypes
import datetime
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import random
import re
import shutil
import signal
import sqlite3
import subprocess
import sys

if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w")
    except Exception:
        pass
else:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w")
    except Exception:
        pass
else:
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import threading
import time
import uuid
import winreg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image, ImageDraw
import psutil
import pystray
import requests
import certifi


def init_ssl_ca_bundle() -> str:

    try:

        for var in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
            val = os.environ.get(var)
            if val and not os.path.exists(val):
                os.environ.pop(var, None)


        src_bundle = None
        try:
            cand = certifi.where()
            if cand and os.path.exists(cand):
                src_bundle = cand
        except Exception:
            pass

        if not src_bundle and hasattr(sys, "_MEIPASS"):
            cand = os.path.join(sys._MEIPASS, "certifi", "cacert.pem")
            if os.path.exists(cand):
                src_bundle = cand


        safe_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "WuwaTappoAutoClaim")
        os.makedirs(safe_dir, exist_ok=True)
        persistent_bundle = os.path.join(safe_dir, "cacert.pem")

        if src_bundle and os.path.exists(src_bundle):
            try:
                if not os.path.exists(persistent_bundle) or os.path.getsize(persistent_bundle) != os.path.getsize(src_bundle):
                    shutil.copy2(src_bundle, persistent_bundle)
            except Exception:
                pass

        final_bundle = persistent_bundle if os.path.exists(persistent_bundle) else src_bundle
        if final_bundle and os.path.exists(final_bundle):
            os.environ["REQUESTS_CA_BUNDLE"] = final_bundle
            os.environ["SSL_CERT_FILE"] = final_bundle
            return final_bundle
    except Exception:
        pass
    return None

CA_BUNDLE_PATH = init_ssl_ca_bundle()


PROJECT_NAME = "WuwaTappo AutoClaim"
PROJECT_AUTHOR = "kinne-luu"
APP_VERSION = "1.0.2"


if getattr(sys, "frozen", False):
    WORKSPACE_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", WORKSPACE_DIR)
else:
    WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = WORKSPACE_DIR

CONFIG_FILE = os.path.join(WORKSPACE_DIR, "config.json")
STATS_FILE = os.path.join(WORKSPACE_DIR, "stats.json")
LOG_FILE = os.path.join(WORKSPACE_DIR, "auto_claim.log")

CHEST_COST = 1000
CLICK_GAIN_PER_CHEST = 1000
MIN_BALANCE_MAINTAIN = 5000

SERVICE_BASE = "https://api-wutheringwaves-wuwatappo.kurogames-global.com"


TASK_NAME = "WuwaTappoAutoClaim"
kernel32 = ctypes.windll.kernel32 if os.name == "nt" else None
user32 = ctypes.windll.user32 if os.name == "nt" else None
console_hwnd = None
tray_icon = None
is_window_visible = True
running_flag = True
global_update_view_fn = None
is_setting_active = False

ASSETS_DIR = os.path.join(BUNDLE_DIR, "assets") if os.path.exists(os.path.join(BUNDLE_DIR, "assets")) else os.path.join(WORKSPACE_DIR, "assets")

config_data = {}
min_delay_sec = 5
max_delay_sec = 120
min_chest_interval_sec = 30
chest_delays = {"left": 0, "right": 0}
webhook_url = ""
custom_game_path = ""

# Smart Idle Click Farmer state & config
idle_farm_enabled = False
idle_threshold_sec = 30
farm_session_limit = 15000
farm_max_balance = 0
idle_farm_status = "OFF (Press [F] to Enable)"
is_claiming_chest = False
live_balance_ref = {"total_clicks": 0, "total_consume": 0}

# Session & Lifetime Statistics
_stats_lock = threading.Lock()
session_start_mono = time.monotonic()


def _new_stats_bucket() -> dict:
    return {
        "chests_claimed": 0,
        "new_count": 0,
        "dup_count": 0,
        "farmed_clicks": 0,
        "rarities": {"epic": 0, "rare": 0, "uncommon": 0, "common": 0},
        "types": {"Character": 0, "Accessory": 0, "Emote": 0},
        "recent_claims": [],
    }


session_stats = _new_stats_bucket()
lifetime_stats = _new_stats_bucket()
collection_state = {
    "owned_total": 0,
    "atlas_total": 899,
    "owned_by_type": {"Character": 0, "Accessory": 0, "Emote": 0},
    "atlas_by_type": {"Character": 260, "Accessory": 135, "Emote": 504},
}


def load_lifetime_stats():
    global lifetime_stats
    if not os.path.exists(STATS_FILE):
        return
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        base = _new_stats_bucket()
        for k in ("chests_claimed", "new_count", "dup_count", "farmed_clicks"):
            base[k] = int(raw.get(k, 0) or 0)
        for rk in base["rarities"]:
            base["rarities"][rk] = int((raw.get("rarities") or {}).get(rk, 0) or 0)
        for tk in base["types"]:
            base["types"][tk] = int((raw.get("types") or {}).get(tk, 0) or 0)
        if isinstance(raw.get("recent_claims"), list):
            base["recent_claims"] = raw["recent_claims"][:12]
        with _stats_lock:
            lifetime_stats = base
    except Exception:
        pass


def save_lifetime_stats():
    try:
        with _stats_lock:
            payload = json.loads(json.dumps(lifetime_stats))
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def record_claim_stat(place_name: str, asset_name: str, item_type: str, rarity: str, is_new: bool, qty: int):
    r_key = (rarity or "common").strip().lower()
    if r_key not in ("epic", "rare", "uncommon", "common"):
        r_key = "common"
    t_key = item_type if item_type in ("Character", "Accessory", "Emote") else "Character"
    entry = {
        "time": datetime.datetime.now().strftime("%m-%d %H:%M"),
        "chest": place_name,
        "name": asset_name,
        "type": item_type,
        "rarity": rarity.capitalize() if rarity else "Common",
        "is_new": is_new,
        "qty": qty or 1,
    }
    with _stats_lock:
        for bucket in (session_stats, lifetime_stats):
            bucket["chests_claimed"] += 1
            if is_new is True:
                bucket["new_count"] += 1
            elif is_new is False:
                bucket["dup_count"] += 1
            bucket["rarities"][r_key] = bucket["rarities"].get(r_key, 0) + 1
            if item_type in bucket["types"]:
                bucket["types"][t_key] = bucket["types"].get(t_key, 0) + 1
            bucket["recent_claims"].insert(0, entry)
            bucket["recent_claims"] = bucket["recent_claims"][:12]
    save_lifetime_stats()


def record_farmed_clicks(delta: int, flush_disk: bool = False):
    if delta <= 0:
        return
    with _stats_lock:
        session_stats["farmed_clicks"] += delta
        lifetime_stats["farmed_clicks"] += delta
    if flush_disk:
        save_lifetime_stats()


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]


def get_system_idle_seconds() -> float:
    """Return real OS hardware keyboard/mouse idle duration in seconds (never reset by CDP events)."""
    if os.name != "nt":
        return 0.0
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if user32.GetLastInputInfo(ctypes.byref(lii)):
            tick = kernel32.GetTickCount() & 0xFFFFFFFF
            elapsed_ms = (tick - (lii.dwTime & 0xFFFFFFFF)) & 0xFFFFFFFF
            return elapsed_ms / 1000.0
    except Exception:
        pass
    return 0.0



logger = logging.getLogger("AutoClaim")
logger.setLevel(logging.DEBUG)
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)


class Color:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    GRAY    = "\033[90m"

    # Fastfetch Pastel Colors
    PASTEL_CYAN   = "\033[38;5;117m"
    PASTEL_PINK   = "\033[38;5;218m"
    PASTEL_BLUE   = "\033[38;5;110m"
    PASTEL_GREEN  = "\033[38;5;150m"
    PASTEL_YELLOW = "\033[38;5;222m"
    PASTEL_GRAY   = "\033[38;5;244m"
    BORDER_GRAY   = "\033[38;5;240m"

    RARITY = {
        "epic": "\033[1;95m",
        "rare": "\033[1;94m",
        "uncommon": "\033[1;92m",
        "common": "\033[1;93m",
    }


def set_console_icon():
    """Sets window icon for Console HWND and sets explicit AppUserModelID."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(PROJECT_NAME)
    except Exception:
        pass

    try:
        ico_candidates = [
            os.path.join(ASSETS_DIR, "Zani-Icon.ico"),
            os.path.join(WORKSPACE_DIR, "assets", "Zani-Icon.ico"),
            os.path.join(BUNDLE_DIR, "assets", "Zani-Icon.ico"),
            os.path.join(WORKSPACE_DIR, "Zani-Icon.ico"),
        ]
        ico_path = None
        for p in ico_candidates:
            if p and os.path.exists(p):
                ico_path = p
                break

        if ico_path:
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x00000010
            LR_DEFAULTSIZE = 0x00000040
            h_icon = user32.LoadImageW(None, ico_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h_icon:
                WM_SETICON = 0x0080
                hwnds = get_all_console_hwnds()
                for h in hwnds:
                    user32.SendMessageW(h, WM_SETICON, 0, h_icon)  # ICON_SMALL
                    user32.SendMessageW(h, WM_SETICON, 1, h_icon)  # ICON_BIG
    except Exception as e:
        logger.debug(f"Set console icon error: {e}")


def init_terminal():
    global console_hwnd
    if os.name == "nt":
        try:
            h_stdout = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
                kernel32.SetConsoleMode(h_stdout, mode.value | 0x0004)
            # Disable QuickEdit Mode on stdin so clicking the console never freezes output ("Select ...")
            h_stdin = kernel32.GetStdHandle(-10)
            in_mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_stdin, ctypes.byref(in_mode)):
                ENABLE_QUICK_EDIT_MODE = 0x0040
                ENABLE_EXTENDED_FLAGS = 0x0080
                new_in_mode = (in_mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
                kernel32.SetConsoleMode(h_stdin, new_in_mode)
            kernel32.SetConsoleTitleW(f"{PROJECT_NAME} v{APP_VERSION}")
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
            console_hwnd = kernel32.GetConsoleWindow()
            set_console_icon()
        except Exception:
            pass


ANSI_REGEX = re.compile(r"\x1b\[[0-9;]*m")


def visible_len(s: str) -> int:
    return len(ANSI_REGEX.sub("", s))


def render_banner():
    c = Color
    print(f"\n  {c.PASTEL_CYAN}{c.BOLD}{PROJECT_NAME.upper()}{c.RESET}  {c.PASTEL_GRAY}v{APP_VERSION}{c.RESET}")
    print(f"  {c.BORDER_GRAY}{'─' * 52}{c.RESET}\n")


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def get_token_from_cookies():


    local_state_path = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), r"com.kuro.wuwatappo.global\EBWebView\Local State"
    )
    cookies_path = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), r"com.kuro.wuwatappo.global\EBWebView\Default\Network\Cookies"
    )

    if not (os.path.exists(local_state_path) and os.path.exists(cookies_path)):
        return None

    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            local_state = json.load(f)
        encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])[5:]

        blob_in = DATA_BLOB(
            len(encrypted_key),
            ctypes.cast(ctypes.create_string_buffer(encrypted_key), ctypes.POINTER(ctypes.c_byte)),
        )
        blob_out = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            return None
        master_key = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)

        temp_cookies = os.path.join(os.environ.get("TEMP", ""), f"wuwatappo_ck_{uuid.uuid4().hex[:8]}.db")
        try:
            shutil.copy2(cookies_path, temp_cookies)
        except Exception:
            return None

        conn = sqlite3.connect(temp_cookies)
        cur = conn.cursor()


        version_row = cur.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        version = int(version_row[0]) if version_row else 0

        rows = cur.execute(
            "SELECT host_key, value, encrypted_value FROM cookies WHERE name = 'kuro_infoToken'"
        ).fetchall()
        conn.close()
        try:
            os.remove(temp_cookies)
        except Exception:
            pass

        for host, plain, enc_val in rows:
            if plain:
                return plain
            if enc_val and enc_val[:3] in (b"v10", b"v11"):
                iv = enc_val[3:15]
                ciphertext = enc_val[15:]
                aesgcm = AESGCM(master_key)
                decrypted = aesgcm.decrypt(iv, ciphertext, None)


                if version >= 24:
                    expected_prefix = hashlib.sha256(host.encode("utf-8")).digest()
                    if decrypted[:32] == expected_prefix:
                        decrypted = decrypted[32:]

                token = decrypted.decode("utf-8", errors="ignore").strip()
                if re.fullmatch(r"[a-f0-9]{64}", token):
                    return token


                m = re.search(rb"([a-f0-9]{64})", decrypted)
                if m:
                    return m.group(1).decode("utf-8")
    except Exception as e:
        logger.debug(f"Could not read token from cookies: {e}")
    return None


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
kernel32 = ctypes.windll.kernel32


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_ulong),
        ("PartitionId", ctypes.c_ushort),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
    ]


def auto_detect_token_from_memory():

    tappo_pids = []
    my_pid = os.getpid()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["pid"] == my_pid:
                continue
            name = (p.info["name"] or "").lower()
            if name == "wuwatappo.exe":
                tappo_pids.append(p.info["pid"])
            elif name == "msedgewebview2.exe":
                try:
                    cmd = " ".join(p.cmdline() or []).lower()
                    if "wuwatappo" in cmd:
                        tappo_pids.append(p.info["pid"])
                except Exception:
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    patterns = [
        re.compile(rb"kuro_infoToken=([a-f0-9]{64})"),
        re.compile(rb"kuro_infoToken[\"':\s=]+([a-f0-9]{64})"),
    ]
    for pid in tappo_pids:
        h = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            continue
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION()
        while kernel32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            if mbi.State == 0x1000 and (mbi.Protect & 0xEE) and not (mbi.Protect & 0x100):
                buf = (ctypes.c_char * mbi.RegionSize)()
                nread = ctypes.c_size_t()
                if kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, mbi.RegionSize, ctypes.byref(nread)):
                    data = bytes(buf)[: nread.value]
                    for pat in patterns:
                        m = pat.search(data)
                        if m:
                            kernel32.CloseHandle(h)
                            return m.group(1).decode("utf-8")
            addr += mbi.RegionSize
        kernel32.CloseHandle(h)
    return None


def auto_detect_cid():

    appdata = os.environ.get("LOCALAPPDATA", "")
    path = os.path.join(appdata, r"com.kuro.wuwatappo.global\EBWebView\Default\Local Storage\leveldb")
    if os.path.exists(path):
        for f in os.listdir(path):
            if f.endswith(".ldb") or f.endswith(".log"):
                try:
                    with open(os.path.join(path, f), "rb") as fp:
                        d = fp.read()
                        m = re.search(rb"KURO_YCK_REQ_CID[\s\S]{1,20}?([a-f0-9]{32})", d)
                        if m:
                            return m.group(1).decode("utf-8")
                except Exception:
                    pass
    return None


def create_tray_icon_image():
    candidates = [
        os.path.join(WORKSPACE_DIR, "assets", "Zani-Icon.png"),
        os.path.join(BUNDLE_DIR, "assets", "Zani-Icon.png"),
        os.path.join(WORKSPACE_DIR, "assets", "Zani-Icon.ico"),
        os.path.join(BUNDLE_DIR, "assets", "Zani-Icon.ico"),
        os.path.join(WORKSPACE_DIR, "Zani-Icon.png"),
        os.path.join(BUNDLE_DIR, "Zani-Icon.png"),
        os.path.join(WORKSPACE_DIR, "Zani-Icon.ico"),
        os.path.join(BUNDLE_DIR, "Zani-Icon.ico"),
    ]
    for icon_path in candidates:
        if os.path.exists(icon_path):
            try:
                img = Image.open(icon_path).convert("RGBA")
                return img.resize((64, 64), Image.Resampling.LANCZOS)
            except Exception as e:
                logger.debug(f"Could not load icon {icon_path}: {e}")


    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(18, 140, 126), outline=(255, 215, 0), width=3)
    d.rectangle((16, 26, 48, 48), fill=(243, 156, 18), outline=(255, 255, 255), width=2)
    d.rectangle((14, 20, 50, 26), fill=(230, 126, 34), outline=(255, 255, 255), width=2)
    d.rectangle((29, 28, 35, 36), fill=(255, 215, 0), outline=(0, 0, 0), width=1)
    return img


def dpapi_encrypt(plain_text: str) -> str:


    if os.name != "nt" or not plain_text or plain_text.startswith("dpapi:"):
        return plain_text
    try:
        data = plain_text.encode("utf-8")
        blob_in = DATA_BLOB(
            len(data),
            ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)),
        )
        blob_out = DATA_BLOB()
        if ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), "WuwaToken", None, None, None, 0, ctypes.byref(blob_out)
        ):
            enc_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return "dpapi:" + base64.b64encode(enc_bytes).decode("ascii")
    except Exception as e:
        logger.debug(f"DPAPI encryption failed: {e}")
    return plain_text


def dpapi_decrypt(cipher_str: str) -> str:

    if os.name != "nt" or not cipher_str or not cipher_str.startswith("dpapi:"):
        return cipher_str
    try:
        raw_b64 = cipher_str[6:].strip()
        cipher_bytes = base64.b64decode(raw_b64)
        blob_in = DATA_BLOB(
            len(cipher_bytes),
            ctypes.cast(ctypes.create_string_buffer(cipher_bytes), ctypes.POINTER(ctypes.c_byte)),
        )
        blob_out = DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            plain = ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8")
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return plain
    except Exception as e:
        logger.debug(f"DPAPI decryption failed: {e}")
    return cipher_str


def is_autostart_enabled() -> bool:

    if os.name != "nt":
        return False
    try:
        res = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        return res.returncode == 0
    except Exception:
        return False


def set_autostart(enable: bool) -> bool:

    if os.name != "nt":
        return False
    if enable:
        if getattr(sys, "frozen", False):
            cmd = f'"{sys.executable}"'
        else:
            script = os.path.abspath(__file__)
            py_exe = sys.executable
            cmd = f'"{py_exe}" "{script}"'
        try:
            res = subprocess.run(
                [
                    "schtasks", "/create",
                    "/tn", TASK_NAME,
                    "/tr", cmd,
                    "/sc", "onlogon",
                    "/rl", "highest",
                    "/f",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=0x08000000,
            )
            return res.returncode == 0
        except Exception:
            return False
    else:
        try:
            res = subprocess.run(
                ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=0x08000000,
            )
            return res.returncode == 0
        except Exception:
            return False


def save_config_key(key: str, val):

    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    if key == "token" and isinstance(val, str) and not val.startswith("dpapi:"):
        val = dpapi_encrypt(val)
    cfg[key] = val
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"Failed to save config key {key}: {e}")


def disable_console_close_button():
    pass


def get_all_console_hwnds():
    hwnds = set()
    if os.name != "nt":
        return hwnds
    h = kernel32.GetConsoleWindow()
    if h:
        hwnds.add(h)
        root = user32.GetAncestor(h, 3) # GA_ROOTOWNER = 3
        if root:
            hwnds.add(root)
        parent = user32.GetParent(h)
        if parent:
            hwnds.add(parent)
    return hwnds


def hide_window(notify_user: bool = True):

    global is_window_visible, console_hwnd
    if os.name != "nt":
        return
    hwnds = get_all_console_hwnds()
    for h in hwnds:
        try:
            user32.ShowWindow(h, 0) # SW_HIDE
            ex_style = user32.GetWindowLongW(h, -20)
            user32.SetWindowLongW(h, -20, (ex_style | 0x80) & ~0x40000) # WS_EX_TOOLWINDOW | ~WS_EX_APPWINDOW
            user32.SetWindowPos(h, 0, 0, 0, 0, 0, 0x0027) # SWP_FRAMECHANGED | SWP_HIDEWINDOW
        except Exception:
            pass

    is_window_visible = False
    save_config_key("show_window", False)

    if tray_icon:
        try:
            tray_icon.update_menu()
        except Exception:
            pass

    if notify_user and tray_icon:
        try:
            tray_icon.notify(
                f"{PROJECT_NAME} is running in System Tray.\nClick icon to restore window.",
                PROJECT_NAME,
            )
        except Exception:
            pass


def show_window(icon=None, item=None):

    global is_window_visible, console_hwnd
    if os.name != "nt":
        return
    hwnds = get_all_console_hwnds()
    main_h = None
    for h in hwnds:
        try:
            ex_style = user32.GetWindowLongW(h, -20)
            user32.SetWindowLongW(h, -20, (ex_style & ~0x80) | 0x40000) # ~WS_EX_TOOLWINDOW | WS_EX_APPWINDOW
            user32.SetWindowPos(h, 0, 0, 0, 0, 0, 0x0027)
            user32.ShowWindow(h, 9) # SW_RESTORE
            user32.ShowWindow(h, 5) # SW_SHOW
            main_h = h
        except Exception:
            pass

    if main_h:
        try:
            user32.SetForegroundWindow(main_h)
        except Exception:
            pass

    is_window_visible = True
    save_config_key("show_window", True)

    if tray_icon:
        try:
            tray_icon.update_menu()
        except Exception:
            pass

    if global_update_view_fn:
        global_update_view_fn(in_place=False)


def toggle_window(icon=None, item=None):

    global is_window_visible
    if is_window_visible:
        hide_window(notify_user=True)
    else:
        show_window()


def toggle_autostart(icon=None, item=None):

    current = is_autostart_enabled()
    new_state = not current
    success = set_autostart(new_state)
    if success:
        save_config_key("start_with_windows", new_state)
        msg = "Start with Windows enabled (Task Scheduler Admin)." if new_state else "Start with Windows disabled."
        if tray_icon:
            try:
                tray_icon.update_menu()
                tray_icon.notify(msg, PROJECT_NAME)
            except Exception:
                pass


def exit_from_tray(icon=None, item=None):
    global running_flag
    running_flag = False
    cleanup_app_exit()
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass
    os._exit(0)


def open_log_file(icon=None, item=None):
    """Open the auto_claim.log file with the system default viewer (Notepad)."""
    try:
        if os.name == "nt" and os.path.exists(LOG_FILE):
            os.startfile(LOG_FILE)
    except Exception:
        pass


def toggle_idle_farm(icon=None, item=None):
    global idle_farm_enabled, idle_farm_status
    idle_farm_enabled = not idle_farm_enabled
    save_config_key("idle_farm_enabled", idle_farm_enabled)
    idle_farm_status = "ON · Waiting for idle..." if idle_farm_enabled else "OFF (Press [F] to Enable)"
    logger.info(f"Smart Idle Click Farm {'ENABLED' if idle_farm_enabled else 'DISABLED'} by user.")
    if tray_icon:
        try:
            tray_icon.update_menu()
            tray_icon.notify(
                f"Smart Idle Farm {'enabled' if idle_farm_enabled else 'disabled'}.",
                PROJECT_NAME,
            )
        except Exception:
            pass
    if global_update_view_fn and not is_setting_active:
        global_update_view_fn(in_place=True)


def init_tray():

    global tray_icon
    menu = pystray.Menu(
        pystray.MenuItem(
            lambda item: "Hide Window" if is_window_visible else "Show Window",
            toggle_window,
            default=True,
        ),
        pystray.MenuItem(
            "Idle Auto-Farm",
            toggle_idle_farm,
            checked=lambda item: idle_farm_enabled,
        ),
        pystray.MenuItem("View Logs", open_log_file),
        pystray.MenuItem(
            "Start with Windows",
            toggle_autostart,
            checked=lambda item: is_autostart_enabled(),
        ),
        pystray.MenuItem("Exit", exit_from_tray),
    )
    tray_icon = pystray.Icon(
        "WuwaTappoAutoClaim",
        create_tray_icon_image(),
        PROJECT_NAME,
        menu,
    )
    t = threading.Thread(target=tray_icon.run, daemon=True)
    t.start()


def window_monitor_loop():

    global console_hwnd, is_window_visible
    if os.name != "nt":
        return
    while running_flag:
        time.sleep(0.1)
        if not console_hwnd:
            console_hwnd = kernel32.GetConsoleWindow()
        if is_window_visible:
            hwnds = get_all_console_hwnds()
            for h in hwnds:
                try:
                    if user32.IsIconic(h):
                        hide_window(notify_user=True)
                        break
                except Exception:
                    pass


def prompt_settings():
    global is_setting_active, min_delay_sec, max_delay_sec, min_chest_interval_sec, chest_delays, webhook_url, custom_game_path
    global idle_farm_enabled, idle_threshold_sec, farm_session_limit, farm_max_balance, idle_farm_status
    if is_setting_active:
        return
    is_setting_active = True
    c = Color
    try:
        sys.stdout.write("\033[?25h\n")
        while is_setting_active:
            clear_terminal()
            print(f"\n  {c.BOLD}{c.PASTEL_YELLOW}─── [S] QUICK SETTINGS MENU ───{c.RESET}")
            print(f"  {c.PASTEL_CYAN}[1]{c.RESET} Min Jitter Delay       : {c.WHITE}{min_delay_sec}s{c.RESET}")
            print(f"  {c.PASTEL_CYAN}[2]{c.RESET} Max Jitter Delay       : {c.WHITE}{max_delay_sec}s{c.RESET}")
            print(f"  {c.PASTEL_CYAN}[3]{c.RESET} Min Chest Interval     : {c.WHITE}{min_chest_interval_sec}s{c.RESET}")
            webhook_disp = f"{webhook_url[:22]}...{webhook_url[-8:]}" if webhook_url else "(Disabled)"
            print(f"  {c.PASTEL_CYAN}[4]{c.RESET} Discord Webhook URL    : {c.WHITE}{webhook_disp}{c.RESET}")
            game_disp = custom_game_path if custom_game_path else "(Auto-Detect)"
            print(f"  {c.PASTEL_CYAN}[5]{c.RESET} Custom Game Path       : {c.WHITE}{game_disp}{c.RESET}")
            farm_state_str = f"{c.PASTEL_GREEN}ON{c.RESET}" if idle_farm_enabled else f"{c.PASTEL_GRAY}OFF{c.RESET}"
            print(f"  {c.PASTEL_CYAN}[6]{c.RESET} Smart Idle Click Farm  : {farm_state_str} {c.PASTEL_GRAY}(Wait idle >= {idle_threshold_sec}s){c.RESET}")
            sess_lim_disp = f"{farm_session_limit:,} clicks/session" if farm_session_limit > 0 else "Unlimited"
            bal_cap_disp = f"{farm_max_balance:,} clicks" if farm_max_balance > 0 else "No Cap"
            print(f"  {c.PASTEL_CYAN}[7]{c.RESET} Idle Farm Safety Caps  : {c.WHITE}{sess_lim_disp}{c.RESET} {c.PASTEL_GRAY}│ Max Balance: {bal_cap_disp}{c.RESET}")
            print(f"  {c.PASTEL_CYAN}[0]{c.RESET} Save & Return to Dashboard\n")

            choice = input(f"  {c.BOLD}Select option to edit [0-7]: {c.RESET}").strip()
            if choice == "1":
                val = input(f"  Enter Min Jitter Delay in seconds [{min_delay_sec}]: ").strip()
                if val.isdigit() and int(val) >= 0:
                    min_delay_sec = int(val)
                    if min_delay_sec > max_delay_sec:
                        max_delay_sec = min_delay_sec
                        save_config_key("max_delay_sec", max_delay_sec)
                    save_config_key("min_delay_sec", min_delay_sec)
                    print(f"  {c.PASTEL_GREEN}[+] Min Delay updated to {min_delay_sec}s{c.RESET}")
            elif choice == "2":
                val = input(f"  Enter Max Jitter Delay in seconds [{max_delay_sec}]: ").strip()
                if val.isdigit() and int(val) >= min_delay_sec:
                    max_delay_sec = int(val)
                    save_config_key("max_delay_sec", max_delay_sec)
                    print(f"  {c.PASTEL_GREEN}[+] Max Delay updated to {max_delay_sec}s{c.RESET}")
                elif val.isdigit():
                    print(f"  {c.RED}[!] Max Delay must be >= Min Delay ({min_delay_sec}s){c.RESET}")
                    time.sleep(1.0)
            elif choice == "3":
                val = input(f"  Enter Min Chest Interval in seconds [{min_chest_interval_sec}]: ").strip()
                if val.isdigit() and int(val) >= 0:
                    min_chest_interval_sec = int(val)
                    save_config_key("min_chest_interval_sec", min_chest_interval_sec)
                    print(f"  {c.PASTEL_GREEN}[+] Min Chest Interval updated to {min_chest_interval_sec}s{c.RESET}")
            elif choice == "4":
                val = input("  Enter Discord Webhook URL (leave blank to disable): ").strip().strip('"\'')
                webhook_url = val
                save_config_key("discord_webhook", webhook_url)
                print(f"  {c.PASTEL_GREEN}[+] Discord Webhook updated!{c.RESET}")
            elif choice == "5":
                val = input("  Enter WuwaTappo.exe Path or Directory (leave blank for auto-detect): ").strip().strip('"\'')
                custom_game_path = val
                save_config_key("game_path", custom_game_path)
                print(f"  {c.PASTEL_GREEN}[+] Custom Game Path updated!{c.RESET}")
            elif choice == "6":
                toggle = input(f"  Enable Smart Idle Farm? (y/n) [{'y' if idle_farm_enabled else 'n'}]: ").strip().lower()
                if toggle in ("y", "yes", "1", "on"):
                    idle_farm_enabled = True
                elif toggle in ("n", "no", "0", "off"):
                    idle_farm_enabled = False
                save_config_key("idle_farm_enabled", idle_farm_enabled)
                idle_farm_status = "ON · Waiting for idle..." if idle_farm_enabled else "OFF (Press [F] to Enable)"
                val = input(f"  Idle wait before farming (seconds, min 10) [{idle_threshold_sec}]: ").strip()
                if val.isdigit():
                    idle_threshold_sec = max(10, int(val))
                    save_config_key("idle_threshold_sec", idle_threshold_sec)
                if tray_icon:
                    try:
                        tray_icon.update_menu()
                    except Exception:
                        pass
            elif choice == "7":
                v1 = input(f"  Max clicks to farm per session (0 = unlimited) [{farm_session_limit}]: ").strip()
                if v1.isdigit():
                    farm_session_limit = max(0, int(v1))
                    save_config_key("farm_session_limit", farm_session_limit)
                v2 = input(f"  Stop farming if balance >= X (0 = no cap) [{farm_max_balance}]: ").strip()
                if v2.isdigit():
                    farm_max_balance = max(0, int(v2))
                    save_config_key("farm_max_balance", farm_max_balance)
            elif choice in ("0", "", "q", "Q"):
                chest_delays["left"] = random.randint(min_delay_sec, max_delay_sec)
                chest_delays["right"] = random.randint(min_delay_sec, max_delay_sec)
                print(f"\n  {c.PASTEL_GREEN}[+] Settings saved. Returning to dashboard...{c.RESET}")
                time.sleep(0.5)
                break
            else:
                print(f"  {c.PASTEL_YELLOW}[!] Invalid choice. Please enter 0 to 7.{c.RESET}")
                time.sleep(0.8)
    except Exception as e:
        logger.debug(f"Prompt settings error: {e}")
    finally:
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        is_setting_active = False
        if global_update_view_fn:
            global_update_view_fn(in_place=False)


def show_logs_view():
    """Display a clean terminal viewer of the most recent log entries with an option to open full log in Notepad."""
    global is_setting_active
    if is_setting_active:
        return
    is_setting_active = True
    c = Color
    try:
        clear_terminal()
        print(f"\n  {c.BOLD}{c.PASTEL_CYAN}─── [L] RECENT LOG ENTRIES ───{c.RESET}")
        print(f"  {c.PASTEL_GRAY}Press [O] to open full log in Notepad │ Any other key to return to Dashboard{c.RESET}\n")

        lines = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                pass

        recent = lines[-16:] if lines else ["  (No logs recorded yet)\n"]
        for l in recent:
            l_str = l.strip()
            if "[INFO]" in l_str:
                print(f"  {c.PASTEL_GREEN}{l_str}{c.RESET}")
            elif "[WARN" in l_str:
                print(f"  {c.PASTEL_YELLOW}{l_str}{c.RESET}")
            elif "[ERROR]" in l_str or "[DEBUG]" in l_str:
                print(f"  {c.PASTEL_PINK}{l_str}{c.RESET}")
            else:
                print(f"  {c.PASTEL_GRAY}{l_str}{c.RESET}")

        print(f"\n  {c.PASTEL_CYAN}[O]{c.RESET} Open full log in Notepad      {c.PASTEL_CYAN}[Any Key]{c.RESET} Return to Dashboard\n")

        import msvcrt
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'o', b'O'):
                    open_log_file()
                break
            time.sleep(0.05)
    finally:
        is_setting_active = False
        if global_update_view_fn:
            global_update_view_fn(in_place=False)


def _mini_bar(cur: int, total: int, width: int = 14) -> str:
    c = Color
    pct = min(1.0, max(0.0, cur / max(1, total)))
    filled = int(pct * width)
    return f"{c.PASTEL_CYAN}{'━' * filled}{c.PASTEL_GRAY}{'─' * (width - filled)}{c.RESET} {c.WHITE}{cur}/{total}{c.RESET} {c.PASTEL_YELLOW}({pct * 100:.1f}%){c.RESET}"


def show_stats_view():
    """Display detailed Collection Progress, Session Stats, All-Time Stats, and Recent Claim History."""
    global is_setting_active, lifetime_stats
    if is_setting_active:
        return
    is_setting_active = True
    c = Color
    try:
        while True:
            clear_terminal()
            with _stats_lock:
                ss = json.loads(json.dumps(session_stats))
                ls = json.loads(json.dumps(lifetime_stats))

            up_sec = int(time.monotonic() - session_start_mono)
            up_h, rem = divmod(up_sec, 3600)
            up_m, up_s = divmod(rem, 60)
            up_str = f"{up_h}h {up_m:02d}m {up_s:02d}s" if up_h else f"{up_m:02d}m {up_s:02d}s"

            print(f"\n  {c.BOLD}{c.PASTEL_CYAN}─── [T] COLLECTION & STATISTICS ───{c.RESET}\n")

            # 1. Collection Progress
            ot = collection_state["owned_total"]
            at = collection_state["atlas_total"]
            ob = collection_state["owned_by_type"]
            ab = collection_state["atlas_by_type"]
            print(f"  {c.BOLD}{c.PASTEL_BLUE}▸ Collection Progress (Atlas){c.RESET}")
            print(f"    Overall     : {_mini_bar(ot, at, 18)}")
            print(f"    Characters  : {_mini_bar(ob.get('Character', 0), ab.get('Character', 260), 18)}")
            print(f"    Accessories : {_mini_bar(ob.get('Accessory', 0), ab.get('Accessory', 135), 18)}")
            print(f"    Emotes      : {_mini_bar(ob.get('Emote', 0), ab.get('Emote', 504), 18)}\n")

            # 2. Session vs All-Time Stats
            def _fmt_bucket(b: dict) -> str:
                tot = b["chests_claimed"]
                nw = b["new_count"]
                dp = b["dup_count"]
                nw_pct = f" ({nw * 100 / tot:.0f}%)" if tot > 0 else ""
                r = b["rarities"]
                return (
                    f"Chests: {c.WHITE}{tot}{c.RESET} │ "
                    f"{c.PASTEL_GREEN}NEW: {nw}{nw_pct}{c.RESET} · {c.PASTEL_GRAY}DUP: {dp}{c.RESET} │ "
                    f"Farmed: {c.PASTEL_CYAN}+{b['farmed_clicks']:,}{c.RESET}\n"
                    f"                  "
                    f"\033[1;95mEpic {r['epic']}\033[0m · "
                    f"\033[1;94mRare {r['rare']}\033[0m · "
                    f"\033[1;92mUncommon {r['uncommon']}\033[0m · "
                    f"\033[1;93mCommon {r['common']}\033[0m"
                )

            print(f"  {c.BOLD}{c.PASTEL_PINK}▸ Session ({up_str}){c.RESET}")
            print(f"    {_fmt_bucket(ss)}\n")
            print(f"  {c.BOLD}{c.PASTEL_YELLOW}▸ All-Time Recorded{c.RESET}")
            print(f"    {_fmt_bucket(ls)}\n")

            # 3. Recent Claim History
            print(f"  {c.BOLD}{c.PASTEL_GREEN}▸ Recent Claims{c.RESET}")
            recent = ls.get("recent_claims") or []
            if not recent:
                print(f"    {c.PASTEL_GRAY}(No chests recorded yet in stats.json){c.RESET}")
            else:
                for item in recent[:6]:
                    tag = f"{c.PASTEL_GREEN}[NEW]{c.RESET}" if item.get("is_new") else f"{c.PASTEL_GRAY}[DUP x{item.get('qty', 1)}]{c.RESET}"
                    rar = (item.get("rarity") or "Common").lower()
                    r_col = c.RARITY.get(rar, c.WHITE)
                    print(f"    {c.PASTEL_GRAY}{item.get('time', '')}{c.RESET} {item.get('chest', '')} {tag} {item.get('type', '')}: {r_col}{item.get('name', '')} ({item.get('rarity', '')}){c.RESET}")

            print(f"\n  {c.PASTEL_CYAN}[R]{c.RESET} Reset All-Time Stats      {c.PASTEL_CYAN}[Any Key]{c.RESET} Return to Dashboard\n")

            import msvcrt
            pressed = None
            while True:
                if msvcrt.kbhit():
                    pressed = msvcrt.getch()
                    break
                time.sleep(0.05)
            if pressed in (b'r', b'R'):
                with _stats_lock:
                    lifetime_stats = _new_stats_bucket()
                save_lifetime_stats()
                continue
            break
    finally:
        is_setting_active = False
        if global_update_view_fn:
            global_update_view_fn(in_place=False)


def console_input_loop():
    global running_flag
    if os.name != "nt":
        return
    import msvcrt
    while running_flag:
        try:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'\x00', b'\xe0'):
                    # Drain special arrow/function key second byte
                    if msvcrt.kbhit():
                        msvcrt.getch()
                    continue
                if ch in (b'h', b'H', b'm', b'M'):
                    hide_window(notify_user=True)
                elif ch in (b'f', b'F'):
                    toggle_idle_farm()
                elif ch in (b't', b'T'):
                    show_stats_view()
                elif ch in (b's', b'S'):
                    prompt_settings()
                elif ch in (b'l', b'L'):
                    show_logs_view()
                elif ch in (b'q', b'Q'):
                    running_flag = False
                    cleanup_app_exit()
                    os._exit(0)
            time.sleep(0.1)
        except Exception:
            time.sleep(0.5)


def parse_cli_args():
    parser = argparse.ArgumentParser(
        prog="WuwaTappoAutoClaim",
        description="Wuwa Tappo Auto Claim - Fastfetch-style CLI Edition with System Tray",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  WuwaTappoAutoClaim.exe                         # Run interactively
  WuwaTappoAutoClaim.exe --status                # Print status snapshot and exit
  WuwaTappoAutoClaim.exe --min-delay 5 --max-delay 30 --interval 15
  WuwaTappoAutoClaim.exe --tray                  # Start minimized in System Tray
  WuwaTappoAutoClaim.exe --token "YOUR_TOKEN"    # Update token
        """
    )
    parser.add_argument("--status", "--info", dest="status_only", action="store_true", help="Print account status and exit")
    parser.add_argument("--min-delay", type=int, help="Minimum random delay in seconds (jitter)")
    parser.add_argument("--max-delay", type=int, help="Maximum random delay in seconds (jitter)")
    parser.add_argument("--interval", type=int, help="Minimum interval in seconds between chests")
    parser.add_argument("--token", type=str, help="Set Bearer Token")
    parser.add_argument("--cid", type=str, help="Set Device CID")
    parser.add_argument("--webhook", type=str, help="Set Discord Webhook URL")
    parser.add_argument("--tray", "--headless", "--hide", dest="start_tray", action="store_true", help="Start directly in System Tray (minimized)")
    parser.add_argument("--no-sync", action="store_true", help="Disable Pet CDP sync")
    parser.add_argument("--idle-farm", action="store_true", help="Enable Smart Idle Click Farm on startup")
    return parser.parse_args()


def load_config(cli_args=None):

    c = Color
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    cid = cfg.get("cid")
    token = None
    token_src = ""

    if cli_args and getattr(cli_args, "token", None):
        token = cli_args.token.strip().strip("'\"")
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        token_src = "CLI Argument"

    if not token:
        token = auto_detect_token_from_memory()
        if token:
            token_src = "RAM Memory"

    if not token:
        token = get_token_from_cookies()
        if token:
            token_src = "WebView2 Cookies"

    if not token:
        raw_token = cfg.get("token")
        if raw_token:
            token = dpapi_decrypt(raw_token)
            if token:
                token_src = "config.json"

    if cli_args and getattr(cli_args, "cid", None):
        cid = cli_args.cid.strip()
        cid_src = "CLI Argument"
    else:
        detected_cid = auto_detect_cid()
        cid_src = "Machine Storage"
        if detected_cid:
            cid = detected_cid
        elif not cid:
            cid = uuid.uuid4().hex
            cid_src = "Generated"
        else:
            cid_src = "config.json"

    if token:
        logger.info(f"Loaded Token from {token_src}: {token[:8]}...{token[-8:]}")
    else:
        print(f"  {c.YELLOW}[!] Token not found automatically.{c.RESET}")
        raw_token = ""
        try:
            if sys.stdin and sys.stdin.isatty():
                raw_token = input("  >> Enter Bearer Token: ").strip().strip("'\"")
        except Exception:
            pass
        if raw_token.lower().startswith("bearer "):
            raw_token = raw_token[7:].strip()
        token = raw_token
        token_src = "User Input"

    global webhook_url, custom_game_path, idle_farm_enabled, idle_threshold_sec, farm_session_limit, farm_max_balance, idle_farm_status
    webhook_url = cfg.get("discord_webhook", "").strip()
    if cli_args and getattr(cli_args, "webhook", None) is not None:
        webhook_url = cli_args.webhook.strip()

    custom_game_path = cfg.get("game_path", "").strip()

    show_window = cfg.get("show_window", True)
    if cli_args and getattr(cli_args, "start_tray", False):
        show_window = False

    start_with_windows = cfg.get("start_with_windows", False)
    min_delay_sec = int(cfg.get("min_delay_sec", 5))
    max_delay_sec = int(cfg.get("max_delay_sec", 60))
    min_chest_interval_sec = int(cfg.get("min_chest_interval_sec", 10))

    idle_farm_enabled = bool(cfg.get("idle_farm_enabled", False))
    if cli_args and getattr(cli_args, "idle_farm", False):
        idle_farm_enabled = True
    idle_threshold_sec = max(10, int(cfg.get("idle_threshold_sec", 30)))
    farm_session_limit = max(0, int(cfg.get("farm_session_limit", 15000)))
    farm_max_balance = max(0, int(cfg.get("farm_max_balance", 0)))
    idle_farm_status = "ON · Waiting for idle..." if idle_farm_enabled else "OFF (Press [F] to Enable)"

    if cli_args:
        if getattr(cli_args, "min_delay", None) is not None:
            min_delay_sec = max(0, cli_args.min_delay)
        if getattr(cli_args, "max_delay", None) is not None:
            max_delay_sec = max(min_delay_sec, cli_args.max_delay)
        if getattr(cli_args, "interval", None) is not None:
            min_chest_interval_sec = max(5, cli_args.interval)

    if start_with_windows and not is_autostart_enabled():
        set_autostart(True)
    elif not start_with_windows and is_autostart_enabled():
        set_autostart(False)

    cfg["token"] = dpapi_encrypt(token) if token else ""
    cfg["cid"] = cid
    cfg["discord_webhook"] = webhook_url
    cfg["game_path"] = custom_game_path
    cfg["show_window"] = show_window
    cfg["start_with_windows"] = start_with_windows
    cfg["min_delay_sec"] = min_delay_sec
    cfg["max_delay_sec"] = max_delay_sec
    cfg["min_chest_interval_sec"] = min_chest_interval_sec
    cfg["idle_farm_enabled"] = idle_farm_enabled
    cfg["idle_threshold_sec"] = idle_threshold_sec
    cfg["farm_session_limit"] = farm_session_limit
    cfg["farm_max_balance"] = farm_max_balance

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return token, cid, webhook_url, token_src, cid_src, show_window, min_delay_sec, max_delay_sec, min_chest_interval_sec


def get_asset_url(asset_name: str) -> str:

    base = "https://wutheringwaves-wuwatappo.kurogames-global.com"
    if not asset_name:
        return ""
    name_lower = asset_name.lower()
    if name_lower.startswith("accessory"):
        return f"{base}/accessory/{asset_name}"
    elif name_lower.startswith("role"):
        return f"{base}/character/{asset_name}"
    elif name_lower.startswith("emote"):
        return f"{base}/emote/{asset_name}"
    return f"{base}/{asset_name}"


def classify_asset_type(asset_type: str = "", asset_name: str = "") -> str:
    t = str(asset_type or "").strip().lower()
    if t in ("character_skin", "character_skin_atlas", "character", "role"):
        return "Character"
    if t in ("accessory", "accessory_atlas"):
        return "Accessory"
    if t in ("emote", "emote_atlas"):
        return "Emote"
    n = str(asset_name or "").strip().lower()
    if n.startswith("role"):
        return "Character"
    if n.startswith("accessory"):
        return "Accessory"
    if n.startswith("emote"):
        return "Emote"
    return t.capitalize() if t else "Item"


def send_discord_webhook(
    webhook_url: str,
    nickname: str,
    place: str,
    asset_name: str,
    rarity: str,
    balance: int,
    left_wait_sec: int,
    right_wait_sec: int,
    asset_type: str = "",
    is_new: bool = None,
    quantity: int = None,
    claim_mode: str = "",
):

    if not webhook_url or not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return

    rarity_lower = rarity.lower() if rarity else "common"
    color_map = {
        "epic": 0x9B59B6,
        "rare": 0x3498DB,
        "uncommon": 0x2ECC71,
        "common": 0xF1C40F,
    }
    embed_color = color_map.get(rarity_lower, 0x5865F2)
    image_url = get_asset_url(asset_name)
    place_label = "Chest #1" if place == "left" else "Chest #2"
    item_type = classify_asset_type(asset_type, asset_name)
    status_tag = "NEW!" if is_new is True else (f"Duplicate (x{quantity})" if is_new is False and quantity else ("Duplicate" if is_new is False else "Claimed"))

    fields = [
        {"name": "Player", "value": nickname, "inline": True},
        {"name": "Chest", "value": place_label, "inline": True},
        {"name": "Status", "value": status_tag, "inline": True},
        {"name": "Type", "value": item_type, "inline": True},
        {"name": "Rarity", "value": rarity.capitalize() if rarity else "Common", "inline": True},
        {"name": "Reward Item", "value": f"`{asset_name}`", "inline": True},
        {"name": "Balance", "value": f"{balance:,} clicks", "inline": True},
    ]
    if claim_mode:
        fields.append({"name": "Mode", "value": claim_mode, "inline": True})
    fields.append({
        "name": "Next Cooldowns",
        "value": f"Left: `{format_duration(left_wait_sec)}` | Right: `{format_duration(right_wait_sec)}`",
        "inline": False,
    })

    embed = {
        "title": f"{place_label} Claimed — {status_tag}",
        "color": embed_color,
        "fields": fields,
        "footer": {
            "text": f"{PROJECT_NAME} v{APP_VERSION} - {PROJECT_AUTHOR}",
        },
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    if image_url:
        embed["thumbnail"] = {"url": image_url}

    payload = {
        "username": f"{PROJECT_NAME} (v{APP_VERSION})",
        "avatar_url": "https://aki-gm-resources-back.aki-game.net/head_photo/82001501.png",
        "embeds": [embed],
    }

    try:
        global CA_BUNDLE_PATH
        req_kwargs = {"json": payload, "timeout": 8}
        if CA_BUNDLE_PATH and os.path.exists(CA_BUNDLE_PATH):
            req_kwargs["verify"] = CA_BUNDLE_PATH
        requests.post(webhook_url, **req_kwargs)
    except Exception as e:
        logger.debug(f"Failed to send Discord webhook: {e}")


class WuwaTappoClient:
    def __init__(self, token, cid):
        self.token = token
        self.cid = cid
        self.session = requests.Session()
        global CA_BUNDLE_PATH
        if not CA_BUNDLE_PATH or not os.path.exists(CA_BUNDLE_PATH):
            CA_BUNDLE_PATH = init_ssl_ca_bundle()
        if CA_BUNDLE_PATH and os.path.exists(CA_BUNDLE_PATH):
            self.session.verify = CA_BUNDLE_PATH

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "X-BLM-CID": self.cid,
            "X-BLM-FRID": uuid.uuid4().hex,
            "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.choice([128, 129, 130, 131, 132, 133])}.0.0.0 Safari/537.36 Edg/{random.choice([128, 129, 130, 131, 132, 133])}.0.0.0",
            "Origin": "http://tauri.localhost",
            "Referer": "http://tauri.localhost/",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }

    def _safe_request(self, method: str, url: str, **kwargs):

        global CA_BUNDLE_PATH
        kwargs.setdefault("timeout", 10)
        if CA_BUNDLE_PATH and os.path.exists(CA_BUNDLE_PATH):
            kwargs.setdefault("verify", CA_BUNDLE_PATH)

        for attempt in range(2):
            try:
                return self.session.request(method, url, **kwargs)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError) as e:
                if attempt == 0:
                    logger.debug(f"Transient network error ({e}), retrying once...")
                    time.sleep(1.0)
                    self.session = requests.Session()
                    if CA_BUNDLE_PATH and os.path.exists(CA_BUNDLE_PATH):
                        self.session.verify = CA_BUNDLE_PATH
                    continue
                raise
            except OSError as e:
                if "certificate bundle" in str(e).lower() or "cacert" in str(e).lower():
                    logger.warning(f"TLS certificate bundle corrupted or purged by OS ({e}). Repairing persistent bundle...")
                    CA_BUNDLE_PATH = init_ssl_ca_bundle()
                    if CA_BUNDLE_PATH and os.path.exists(CA_BUNDLE_PATH):
                        kwargs["verify"] = CA_BUNDLE_PATH
                        self.session.verify = CA_BUNDLE_PATH
                        return self.session.request(method, url, **kwargs)
                raise

    def try_refresh_token(self) -> bool:

        new_tok = auto_detect_token_from_memory() or get_token_from_cookies()
        if new_tok and new_tok != self.token:
            logger.info(f"Token refreshed automatically: {new_tok[:8]}...{new_tok[-8:]}")
            self.token = new_tok
            save_config_key("token", new_tok)
            global tray_icon
            if tray_icon:
                try:
                    tray_icon.notify("Session token was refreshed automatically.", PROJECT_NAME)
                except Exception:
                    pass
            return True
        return False

    def get_server_time(self):

        r = self._safe_request("GET", f"{SERVICE_BASE}/api/common/activity-config")
        return r.json()["data"]["server_time"]

    def get_user_info(self):

        r = self._safe_request("GET", f"{SERVICE_BASE}/api/frontend/user/me", headers=self._headers())
        res = r.json()
        if res.get("code") in (10002, 10003, 90002):
            logger.warning(f"User info query rejected ({res.get('code')}). Attempting automatic token refresh...")
            if self.try_refresh_token():
                r = self._safe_request("GET", f"{SERVICE_BASE}/api/frontend/user/me", headers=self._headers())
                res = r.json()
            else:
                raise Exception("Session token expired! Please launch or log in to Wuwa Tappo.")
        if res.get("code") != 0:
            raise Exception(f"Account query error: {res.get('message', res)}")
        return res["data"]

    def get_bag_list(self) -> list:
        r = self._safe_request("POST", f"{SERVICE_BASE}/api/frontend/bags/list", headers=self._headers(), json={})
        res = r.json()
        if res.get("code") in (10002, 10003, 90002):
            if self.try_refresh_token():
                r = self._safe_request("POST", f"{SERVICE_BASE}/api/frontend/bags/list", headers=self._headers(), json={})
                res = r.json()
        if res.get("code") != 0:
            return []
        data = res.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("list", "items", "bags", "assets", "appearances"):
                if isinstance(data.get(k), list):
                    return data[k]
            for v in data.values():
                if isinstance(v, list):
                    return v
        return []

    def get_atlas_list(self) -> list:
        try:
            r = self._safe_request("GET", f"{SERVICE_BASE}/api/common/atlas", headers=self._headers())
            res = r.json()
            if res.get("code") == 0 and isinstance(res.get("data"), list):
                return res["data"]
        except Exception as e:
            logger.debug(f"get_atlas_list failed: {e}")
        return []

    def open_chest(self, place, click_num):

        payload = {"place": place, "click_num": click_num}
        r = self._safe_request("POST", f"{SERVICE_BASE}/api/frontend/chests/open", headers=self._headers(), json=payload)
        res = r.json()
        if res.get("code") in (10002, 10003, 90002):
            logger.warning(f"Claim request rejected ({res.get('code')}). Attempting automatic token refresh...")
            if self.try_refresh_token():
                r = self._safe_request("POST", f"{SERVICE_BASE}/api/frontend/chests/open", headers=self._headers(), json=payload)
                res = r.json()
        return res


def build_bag_snapshot(bag_items: list) -> dict:
    snap = {}
    for it in bag_items or []:
        if not isinstance(it, dict):
            continue
        aid = it.get("asset_id") or it.get("id")
        key = f"id:{aid}" if aid else f"name:{it.get('asset_name', '')}"
        snap[key] = {
            "asset_id": aid,
            "asset_name": it.get("asset_name") or it.get("name") or "Unknown",
            "asset_type": it.get("asset_type") or it.get("type") or "",
            "rarity_type": it.get("rarity_type") or it.get("rarity") or "common",
            "quantity": int(it.get("quantity") or it.get("num") or 1),
        }
    return snap


def evaluate_bag_reward(bag_before: dict, asset_id=None, asset_name: str = "", bag_after: dict = None):
    """Determine if a reward is NEW or DUPLICATE (and updated quantity)."""
    if not bag_before and not bag_after:
        return None, None
    key = f"id:{asset_id}" if asset_id else (f"name:{asset_name}" if asset_name else None)
    if key:
        prev = bag_before.get(key)
        curr = (bag_after or {}).get(key)
        if prev is None:
            return True, (curr["quantity"] if curr else 1)
        prev_qty = prev.get("quantity", 0)
        new_qty = curr["quantity"] if curr else (prev_qty + 1)
        return (prev_qty <= 0), new_qty
    # Fallback: diff bag_before vs bag_after
    if bag_after:
        for k, curr in bag_after.items():
            prev = bag_before.get(k)
            if prev is None:
                return True, curr.get("quantity", 1)
            if curr.get("quantity", 0) > prev.get("quantity", 0):
                return False, curr.get("quantity", 1)
    return None, None


def refresh_collection_state(client: WuwaTappoClient, bag_items: list = None, fetch_atlas: bool = False):
    """Update collection_state from bags/list and optionally /api/common/atlas."""
    if fetch_atlas and client:
        atlas_items = client.get_atlas_list()
        if atlas_items:
            at_by_type = {"Character": 0, "Accessory": 0, "Emote": 0}
            for it in atlas_items:
                if not isinstance(it, dict):
                    continue
                cat = classify_asset_type(it.get("asset_type", ""), it.get("asset_name", ""))
                if cat in at_by_type:
                    at_by_type[cat] += 1
            collection_state["atlas_total"] = len(atlas_items)
            collection_state["atlas_by_type"] = at_by_type

    if bag_items is None and client:
        bag_items = client.get_bag_list()
    if bag_items is not None:
        ow_by_type = {"Character": 0, "Accessory": 0, "Emote": 0}
        owned_count = 0
        for it in bag_items:
            if not isinstance(it, dict):
                continue
            if int(it.get("quantity") or it.get("num") or 1) <= 0:
                continue
            owned_count += 1
            cat = classify_asset_type(it.get("asset_type", ""), it.get("asset_name", ""))
            if cat in ow_by_type:
                ow_by_type[cat] += 1
        collection_state["owned_total"] = owned_count
        collection_state["owned_by_type"] = ow_by_type


def format_duration(seconds: int) -> str:

    m, s = divmod(max(0, int(seconds)), 60)
    if m > 0:
        return f"{m:02d}m {s:02d}s"
    return f"{s:02d}s"


def ts_to_str(ts_ms: int) -> str:

    if ts_ms <= 0:
        return "READY"
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000)
    return dt.strftime("%H:%M:%S")


def is_app_running() -> bool:

    my_pid = os.getpid()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["pid"] == my_pid:
                continue
            name = (p.info["name"] or "").lower()
            if name == "wuwatappo.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False





def is_admin() -> bool:

    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_admin():
    # Process runs directly in user desktop session to prevent UAC terminal flash and browser isolation
    pass


def find_wuwa_tappo_exe() -> str:
    # 1. Custom path tu config
    global custom_game_path
    if custom_game_path and os.path.exists(custom_game_path):
        if os.path.isdir(custom_game_path):
            cand = os.path.join(custom_game_path, "WuwaTappo.exe")
            if os.path.exists(cand):
                return cand
        elif os.path.isfile(custom_game_path) and custom_game_path.lower().endswith("wuwatappo.exe"):
            return custom_game_path

    # 2. Process dang chay tren he thong
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            if (p.info["name"] or "").lower() == "wuwatappo.exe":
                if p.info.get("exe") and os.path.exists(p.info["exe"]):
                    return p.info["exe"]
        except Exception:
            pass

    # 3. Windows Registry Uninstall Keys (Tu dong phat hien tren moi may tinh)
    if os.name == "nt":
        reg_roots = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for root, subkey in reg_roots:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for i in range(count):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as app_key:
                                try:
                                    name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                                except Exception:
                                    name = ""
                                if "wuwatappo" in name.lower() or "wuwa tappo" in name.lower():
                                    for val_name in ("InstallLocation", "DisplayIcon"):
                                        try:
                                            loc, _ = winreg.QueryValueEx(app_key, val_name)
                                            if loc:
                                                loc = loc.split(",")[0].strip('"\'')
                                                if os.path.isdir(loc):
                                                    cand = os.path.join(loc, "WuwaTappo.exe")
                                                    if os.path.exists(cand):
                                                        return cand
                                                elif os.path.isfile(loc) and loc.lower().endswith("wuwatappo.exe"):
                                                    return loc
                                        except Exception:
                                            pass
                        except Exception:
                            continue
            except Exception:
                pass

    # 4. Quet qua cac o dia pho bien (C:\, D:\, E:\, ...)
    for drive_letter in "CDEFGHIJ":
        d = f"{drive_letter}:\\"
        if os.path.exists(d):
            cands = [
                os.path.join(d, "Games", "WuwaTappoGlobal", "WuwaTappo.exe"),
                os.path.join(d, "Program Files", "WuwaTappoGlobal", "WuwaTappo.exe"),
                os.path.join(d, "Program Files (x86)", "WuwaTappoGlobal", "WuwaTappo.exe"),
                os.path.join(d, "WuwaTappoGlobal", "WuwaTappo.exe"),
            ]
            for c in cands:
                if os.path.exists(c):
                    return c

    # 5. LocalAppData Programs
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        cand = os.path.join(local_app, "Programs", "WuwaTappoGlobal", "WuwaTappo.exe")
        if os.path.exists(cand):
            return cand

    return None


POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments"
CDP_PORT = 19222
pet_sync_enabled = True


def is_admin() -> bool:
    """Check if the process is running with Administrator privileges."""
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_admin():
    """Prompt Windows UAC dialog to request Administrator privileges if not elevated."""
    if os.name == "nt" and not is_admin():
        logger.info("Requesting Administrator elevation via UAC...")
        args_str = " ".join([f'"{a}"' for a in sys.argv[1:]])
        if getattr(sys, "frozen", False):
            params = args_str if args_str else None
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, WORKSPACE_DIR, 1
            )
        else:
            script = os.path.abspath(__file__)
            params = f'"{script}" {args_str}'.strip()
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, WORKSPACE_DIR, 1
            )
        sys.exit(0)


def setup_pet_sync():
    """Temporarily apply WebView2 debugging policy ONLY for WuwaTappo.exe (required because
    Tauri v2 sets AdditionalBrowserArguments programmatically, which overrides env vars).
    Cleaned up immediately after CDP binds and on exit.
    """
    if os.name != "nt":
        return
    arg = f"--remote-debugging-port={CDP_PORT} --remote-allow-origins=*"
    for root, name in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
        try:
            key = winreg.CreateKey(root, POLICY_KEY)
            winreg.SetValueEx(key, "WuwaTappo.exe", 0, winreg.REG_SZ, arg)
            try:
                winreg.DeleteValue(key, "*")
            except Exception:
                pass
            winreg.CloseKey(key)
        except Exception as e:
            logger.debug(f"Failed to write {name} policy: {e}")


def cleanup_registry_policy():
    """Remove any leftover WebView2 debugging registry keys (HKLM and HKCU) for zero footprint."""
    if os.name != "nt":
        return
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(root, POLICY_KEY, 0, winreg.KEY_SET_VALUE)
            for val in ("WuwaTappo.exe", "*"):
                try:
                    winreg.DeleteValue(key, val)
                except Exception:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass
        try:
            winreg.DeleteKey(root, POLICY_KEY)
        except Exception:
            pass


def is_cdp_ready() -> bool:
    """Check if WebView2 CDP debugging port is accessible."""
    try:
        resp = requests.get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=0.6)
        return resp.status_code == 200
    except Exception:
        return False


def find_cdp_main_target() -> str:
    """Return WebSocket debugger URL for ONLY the main Wuwa Tappo pet window (index.html#/)."""
    try:
        resp = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=1.0)
        targets = resp.json()
    except Exception:
        return None

    fallback_ws = None
    for t in targets:
        if t.get("type") != "page":
            continue
        ws_url = t.get("webSocketDebuggerUrl")
        if not ws_url:
            continue
        url = (t.get("url") or "").lower()
        if "tauri.localhost" not in url and "wuwatappo" not in (t.get("title") or "").lower():
            continue
        # Skip secondary windows (panel, login, toast, update, maintenance)
        if any(sub in url for sub in ("#/panel", "#/login", "#/toast", "#/update", "#/maintenance")):
            continue
        if url.endswith("#/") or url.endswith("index.html") or "index.html#/" in url:
            return ws_url
        if not fallback_ws:
            fallback_ws = ws_url
    return fallback_ws


def restart_pet_if_needed():
    """Ensure running Wuwa Tappo has CDP port open for Native In-App Auto-Click."""
    global pet_sync_enabled
    c = Color
    if not pet_sync_enabled:
        return
    if not is_app_running():
        print(f"  {c.PASTEL_GRAY}[*] Wuwa Tappo is not running -> Headless API Mode.{c.RESET}", flush=True)
        logger.info("Wuwa Tappo is not running — starting in Clean Headless API Mode.")
        return
    if is_cdp_ready() and find_cdp_main_target():
        print(f"  {c.PASTEL_GREEN}[+] Connected to Wuwa Tappo CDP port {CDP_PORT} (Native Click Mode).{c.RESET}", flush=True)
        logger.info(f"Connected to existing Wuwa Tappo CDP port {CDP_PORT} (Native Click Mode).")
        cleanup_registry_policy()
        return

    print(f"  {c.PASTEL_CYAN}[*] Restarting Wuwa Tappo to attach CDP port {CDP_PORT}...{c.RESET}", flush=True)
    logger.info(f"Restarting Wuwa Tappo with CDP port {CDP_PORT} for Native In-App Auto-Click...")
    setup_pet_sync()
    app_exe = None
    tappo_pids = set()
    my_pid = os.getpid()

    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            if p.info["pid"] == my_pid:
                continue
            name = (p.info["name"] or "").lower()
            if name == "wuwatappo.exe":
                tappo_pids.add(p.info["pid"])
                if p.info.get("exe") and not app_exe:
                    app_exe = p.info["exe"]
                p.kill()
        except Exception:
            pass

    for p in psutil.process_iter(["pid", "name", "ppid", "cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            cmd = " ".join(p.info["cmdline"] or []).lower()
            if "msedgewebview2" in name:
                if p.info["ppid"] in tappo_pids or "com.kuro.wuwatappo" in cmd:
                    p.kill()
        except Exception:
            pass

    time.sleep(1.5)

    if not app_exe or not os.path.exists(app_exe):
        app_exe = find_wuwa_tappo_exe()

    if app_exe and os.path.exists(app_exe):
        try:
            env = os.environ.copy()
            env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={CDP_PORT} --remote-allow-origins=*"
            cwd = os.path.dirname(app_exe)
            subprocess.Popen([app_exe], env=env, cwd=cwd)
            for sec in range(1, 21):
                time.sleep(1)
                sys.stdout.write(f"\r  {c.PASTEL_GRAY}[*] Waiting for Wuwa Tappo CDP... ({sec}s/20s){c.RESET}")
                sys.stdout.flush()
                if is_cdp_ready() and find_cdp_main_target():
                    cleanup_registry_policy()
                    print(f"\r  {c.PASTEL_GREEN}[+] Wuwa Tappo CDP port {CDP_PORT} ready (Native Click Mode)!   {c.RESET}", flush=True)
                    logger.info(f"Wuwa Tappo Pet CDP port {CDP_PORT} ready (Native Click Mode)!")
                    return
            cleanup_registry_policy()
            print(f"\r  {c.PASTEL_YELLOW}[!] Wuwa Tappo started, but CDP port {CDP_PORT} did not respond.  {c.RESET}", flush=True)
            logger.warning(f"Wuwa Tappo started, but CDP port {CDP_PORT} did not respond within 20s.")
        except Exception as e:
            cleanup_registry_policy()
            print(f"\n  {c.RED}[-] Could not relaunch Wuwa Tappo: {e}{c.RESET}", flush=True)
            logger.warning(f"Could not relaunch Wuwa Tappo with CDP: {e}")


def get_pet_live_state() -> dict:
    """Read live state (click counts, chest button readiness) from the main Pet window via CDP."""
    ws_url = find_cdp_main_target()
    if not ws_url:
        return None
    try:
        import websockets

        inspect_js = """
        (() => {
            const leftBtn = document.querySelector('.reward-anchor--left button.reward-btn');
            const rightBtn = document.querySelector('.reward-anchor--right button.reward-btn');
            let storeData = null;
            try {
                const app = document.querySelector('#app');
                const pinia = app?.__vue_app__?.config?.globalProperties?.$pinia;
                const store = pinia?._s?.get('GlobalState');
                if (store) {
                    storeData = {
                        isLoggedIn: !!store.isLoggedIn,
                        totalClickCount: Number(store.totalClickCount ?? 0),
                        cumulativeClickCount: Number(store.cumulativeClickCount ?? 0),
                        localClickCount: Number(store.localClickCount ?? 0),
                        serverClickTotal: Number(store.userInfo?.total_click_count ?? 0),
                        serverClickConsume: Number(store.userInfo?.total_click_consume ?? 0),
                        leftTs: Number(store.userInfo?.left_treasure_chest ?? 0),
                        rightTs: Number(store.userInfo?.right_treasure_chest ?? 0),
                    };
                }
            } catch (e) {}
            return {
                leftReady: !!(leftBtn && !leftBtn.disabled),
                rightReady: !!(rightBtn && !rightBtn.disabled),
                store: storeData,
            };
        })();
        """

        async def _query():
            async with websockets.connect(ws_url, close_timeout=2, max_size=2 * 1024 * 1024) as ws:
                await ws.send(json.dumps({
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {"expression": inspect_js, "returnByValue": True},
                }))
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.2, deadline - time.monotonic()))
                    msg = json.loads(raw)
                    if msg.get("id") == 1:
                        return msg.get("result", {}).get("result", {}).get("value")
            return None

        return asyncio.run(_query())
    except Exception as e:
        logger.debug(f"get_pet_live_state error: {e}")
        return None


def claim_chest_via_cdp(place: str, timeout_sec: float = 10.0) -> dict:
    """Trigger the real in-app chest button click via CDP and capture the exact /chests/open response.
    Zero Page.reload, zero click desync (70003/80022), full animation + NEW bag badge!
    Returns dict: {"status": "ok"|"api_error"|"not_ready"|"error", "response": ..., "detail": ...}
    """
    ws_url = find_cdp_main_target()
    if not ws_url:
        return {"status": "error", "detail": "CDP main target not found"}

    selector = f".reward-anchor--{place} button.reward-btn"
    click_js = f"""
    (() => {{
        const btn = document.querySelector('{selector}');
        if (!btn) return {{ clicked: false, reason: 'button_not_found' }};
        if (btn.disabled) return {{ clicked: false, reason: 'button_disabled' }};
        btn.click();
        return {{ clicked: true }};
    }})();
    """

    try:
        import websockets

        async def _run():
            async with websockets.connect(ws_url, close_timeout=2, max_size=4 * 1024 * 1024) as ws:
                # 1. Enable CDP Network events to capture exact api/frontend/chests/open response
                await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
                # 2. Click the real chest button inside Vue app
                await ws.send(json.dumps({
                    "id": 2,
                    "method": "Runtime.evaluate",
                    "params": {"expression": click_js, "returnByValue": True},
                }))

                chest_req_id = None
                body_requested = False
                click_confirmed = False
                deadline = time.monotonic() + timeout_sec

                try:
                    while time.monotonic() < deadline:
                        rem = max(0.2, deadline - time.monotonic())
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=rem)
                        except asyncio.TimeoutError:
                            break
                        msg = json.loads(raw)

                        if msg.get("id") == 2:
                            val = msg.get("result", {}).get("result", {}).get("value") or {}
                            if not val.get("clicked"):
                                return {"status": "not_ready", "detail": val.get("reason", "not_clickable")}
                            click_confirmed = True

                        elif msg.get("method") == "Network.responseReceived":
                            params = msg.get("params", {})
                            url = (params.get("response", {}).get("url") or "").lower()
                            if "api/frontend/chests/open" in url:
                                chest_req_id = params.get("requestId")

                        elif msg.get("method") == "Network.loadingFinished" and chest_req_id and not body_requested:
                            if msg.get("params", {}).get("requestId") == chest_req_id:
                                body_requested = True
                                await ws.send(json.dumps({
                                    "id": 3,
                                    "method": "Network.getResponseBody",
                                    "params": {"requestId": chest_req_id},
                                }))

                        elif msg.get("id") == 3:
                            res_obj = msg.get("result") or {}
                            body_str = res_obj.get("body", "")
                            if res_obj.get("base64Encoded"):
                                body_str = base64.b64decode(body_str).decode("utf-8", errors="replace")
                            parsed = json.loads(body_str) if body_str else {}
                            if parsed.get("code") == 0:
                                return {"status": "ok", "response": parsed}
                            return {"status": "api_error", "response": parsed, "detail": parsed.get("message", str(parsed))}
                finally:
                    try:
                        await ws.send(json.dumps({"id": 99, "method": "Network.disable"}))
                    except Exception:
                        pass

                if click_confirmed:
                    return {"status": "clicked_no_body", "detail": "Clicked button in Pet UI; timed out waiting for network body"}
                return {"status": "error", "detail": "Timed out before click confirmation"}

        return asyncio.run(_run())
    except Exception as e:
        logger.debug(f"claim_chest_via_cdp error: {e}")
        return {"status": "error", "detail": str(e)}


def idle_farm_worker():
    """Smart Anti-Ban Idle Click Farmer:
    - Uses real OS GetLastInputInfo() (never reset by our CDP claps, stops within <100ms on mouse/key touch).
    - Emits native Tauri 'global-clap-mouse' inside Pet WebView2 via CDP (zero OS SendInput / anti-cheat safe).
    - 3-layer human rhythm: natural log-normal/triangular intervals (~2.5-4.2 CPS), short bursts (8-26 clicks)
      with micro-pauses (3.5-11.5s), and periodic macro breaks (45-110s every 6-12 mins).
    - Respects session click limit, max balance cap, and pauses automatically while claiming chests.
    """
    global idle_farm_status
    clap_expr = "window.__TAURI_INTERNALS__?.invoke('plugin:event|emit', { event: 'global-clap-mouse', payload: null })"
    read_store_expr = """
    (() => {
        const s = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia?._s?.get('GlobalState');
        if (!s) return null;
        return {
            cum: Number(s.cumulativeClickCount ?? 0),
            cons: Number(s.userInfo?.total_click_consume ?? 0),
            bal: Number(s.totalClickCount ?? 0),
        };
    })()
    """

    active_streak_start = 0.0
    next_macro_break_sec = random.randint(360, 720)

    def _interruptible_wait(duration: float, status_prefix: str = "") -> bool:
        """Wait while checking every 0.2s if user became active, disabled farm, or app exited."""
        global idle_farm_status
        end_m = time.monotonic() + duration
        while running_flag and time.monotonic() < end_m:
            if not idle_farm_enabled:
                idle_farm_status = "OFF (Press [F] to Enable)"
                return False
            if get_system_idle_seconds() < idle_threshold_sec:
                return False
            if status_prefix:
                rem = max(1, int(end_m - time.monotonic()))
                with _stats_lock:
                    fc = session_stats["farmed_clicks"]
                idle_farm_status = f"ON · {status_prefix} ({rem}s) │ +{fc:,}"
            time.sleep(min(0.2, max(0.05, end_m - time.monotonic())))
        return running_flag and idle_farm_enabled

    while running_flag:
        try:
            if not idle_farm_enabled:
                idle_farm_status = "OFF (Press [F] to Enable)"
                active_streak_start = 0.0
                time.sleep(0.5)
                continue

            with _stats_lock:
                sess_farmed = session_stats["farmed_clicks"]

            if farm_session_limit > 0 and sess_farmed >= farm_session_limit:
                idle_farm_status = f"ON · Session cap reached (+{sess_farmed:,}/{farm_session_limit:,})"
                active_streak_start = 0.0
                time.sleep(2.0)
                continue

            cur_bal = live_balance_ref["total_clicks"] - live_balance_ref["total_consume"]
            if farm_max_balance > 0 and cur_bal >= farm_max_balance:
                idle_farm_status = f"ON · Balance cap reached ({cur_bal:,} >= {farm_max_balance:,})"
                active_streak_start = 0.0
                time.sleep(2.0)
                continue

            if is_claiming_chest:
                idle_farm_status = f"ON · Paused (Claiming chest) │ +{sess_farmed:,}"
                time.sleep(0.5)
                continue

            idle_sec = get_system_idle_seconds()
            if idle_sec < idle_threshold_sec:
                active_streak_start = 0.0
                idle_farm_status = f"ON · Standby (User active, idle {int(idle_sec)}s/{idle_threshold_sec}s) │ +{sess_farmed:,}"
                time.sleep(0.6)
                continue

            ws_url = find_cdp_main_target() if (is_app_running() and is_cdp_ready()) else None
            if not ws_url:
                idle_farm_status = f"ON · Waiting for Pet CDP... │ +{sess_farmed:,}"
                active_streak_start = 0.0
                time.sleep(2.0)
                continue

            # Macro break check (every 6-12 mins of active idle farming -> rest 45-110s)
            now_m = time.monotonic()
            if active_streak_start <= 0.0:
                active_streak_start = now_m
                next_macro_break_sec = random.randint(360, 720)
            elif (now_m - active_streak_start) >= next_macro_break_sec:
                break_dur = random.randint(45, 110)
                logger.debug(f"[IdleFarm] Taking natural macro break for {break_dur}s.")
                _interruptible_wait(break_dur, "Natural break")
                active_streak_start = time.monotonic()
                next_macro_break_sec = random.randint(360, 720)
                continue

            # Execute one human-like burst (8-26 clicks) over a single CDP WebSocket
            burst_target = random.randint(8, 26)
            if farm_session_limit > 0:
                burst_target = min(burst_target, max(1, farm_session_limit - sess_farmed))

            import websockets

            async def _run_burst(target_count: int):
                global idle_farm_status
                done_in_burst = 0
                msg_id = 1
                async with websockets.connect(ws_url, close_timeout=1.5, max_size=1024 * 1024) as ws:
                    for _ in range(target_count):
                        if not (running_flag and idle_farm_enabled) or is_claiming_chest:
                            break
                        if get_system_idle_seconds() < idle_threshold_sec:
                            break
                        if farm_max_balance > 0 and (live_balance_ref["total_clicks"] - live_balance_ref["total_consume"] + done_in_burst) >= farm_max_balance:
                            break

                        await ws.send(json.dumps({
                            "id": msg_id,
                            "method": "Runtime.evaluate",
                            "params": {"expression": clap_expr, "returnByValue": True},
                        }))
                        try:
                            await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except Exception:
                            break
                        msg_id += 1
                        done_in_burst += 1
                        record_farmed_clicks(1, flush_disk=False)

                        with _stats_lock:
                            fc_now = session_stats["farmed_clicks"]
                        idle_farm_status = f"ON · Farming burst ({done_in_burst}/{target_count}) │ +{fc_now:,} clicks"

                        # Human cadence: 12% quick double-tap (0.13-0.17s), 88% natural rhythm (0.18-0.56s, mode 0.27s)
                        if random.random() < 0.12:
                            delay = random.uniform(0.13, 0.17)
                        else:
                            delay = random.triangular(0.18, 0.56, 0.27)
                        await asyncio.sleep(delay)

                    # Read updated live click totals from Pinia store at end of burst
                    if done_in_burst > 0:
                        await ws.send(json.dumps({
                            "id": msg_id,
                            "method": "Runtime.evaluate",
                            "params": {"expression": read_store_expr, "returnByValue": True},
                        }))
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            val = json.loads(raw).get("result", {}).get("result", {}).get("value")
                            if isinstance(val, dict) and val.get("cum", 0) > 0:
                                live_balance_ref["total_clicks"] = max(live_balance_ref["total_clicks"], int(val["cum"]))
                                if val.get("cons", 0) > 0:
                                    live_balance_ref["total_consume"] = max(live_balance_ref["total_consume"], int(val["cons"]))
                        except Exception:
                            pass
                return done_in_burst

            burst_done = asyncio.run(_run_burst(burst_target))
            if burst_done > 0:
                save_lifetime_stats()

            # Natural micro-pause between bursts (3.5s - 11.5s)
            if idle_farm_enabled and get_system_idle_seconds() >= idle_threshold_sec:
                pause_sec = random.uniform(3.5, 11.5)
                _interruptible_wait(pause_sec, "Burst rest")
        except Exception as e:
            logger.debug(f"idle_farm_worker error: {e}")
            time.sleep(2.0)


def cleanup_app_exit():
    save_lifetime_stats()
    cleanup_registry_policy()
    try:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
    except Exception:
        pass

    global tray_icon
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass


atexit.register(cleanup_app_exit)


def _signal_handler(sig, frame):
    cleanup_app_exit()
    sys.exit(0)


try:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _signal_handler)
except Exception:
    pass

if os.name == "nt":
    try:
        _PHANDLER = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)
        def _console_ctrl(ctrl_type):
            global running_flag
            running_flag = False
            cleanup_app_exit()
            os._exit(0)
            return True
        _ctrl_proc = _PHANDLER(_console_ctrl)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_ctrl_proc, True)
    except Exception:
        pass


def build_banner_lines() -> list:
    c = Color
    return [
        f"\n  {c.BOLD}{c.PASTEL_CYAN}{PROJECT_NAME.upper()}{c.RESET} {c.PASTEL_GRAY}v{APP_VERSION}{c.RESET}",
        f"  {c.BORDER_GRAY}{'─' * 52}{c.RESET}",
    ]


def build_dashboard_lines(
    nickname: str,
    balance: int,
    total_clicks: int,
    total_consume: int,
    left_ts: int,
    right_ts: int,
    now_ts: int,
    app_running: bool = False,
    token_str: str = "",
    cid_str: str = "",
    has_webhook: bool = False,
    delays: dict = None,
    current_action: str = "Monitoring",
    min_delay: int = 5,
    max_delay: int = 60,
    interval: int = 10,
    total_duration: int = 1800,
    last_claim_msg: str = "",
    claim_mode: str = "",
) -> list:
    c = Color
    delays = delays or {"left": 0, "right": 0}

    # Thoi gian goc Server
    orig_wait_left = max(0, int((left_ts - now_ts) / 1000))
    orig_wait_right = max(0, int((right_ts - now_ts) / 1000))
    jitter_left = delays.get("left", 0)
    jitter_right = delays.get("right", 0)

    # Thoi gian thuc te mo (da cong jitter)
    target_left_ts = left_ts + (jitter_left * 1000)
    target_right_ts = right_ts + (jitter_right * 1000)
    wait_left = max(0, int((target_left_ts - now_ts) / 1000))
    wait_right = max(0, int((target_right_ts - now_ts) / 1000))

    if orig_wait_left == 0:
        if wait_left == 0:
            left_status = f"{c.PASTEL_GREEN}READY TO CLAIM{c.RESET}"
        else:
            left_status = f"{c.PASTEL_GREEN}SPAWNED{c.RESET} {c.PASTEL_YELLOW}(claim in {wait_left}s){c.RESET} {c.PASTEL_GRAY}(+{jitter_left}s jitter){c.RESET}"
    else:
        left_status = f"{c.WHITE}{ts_to_str(left_ts)}{c.RESET} {c.PASTEL_YELLOW}in {format_duration(orig_wait_left)}{c.RESET} {c.PASTEL_GRAY}(+{jitter_left}s jitter){c.RESET}"

    if orig_wait_right == 0:
        if wait_right == 0:
            right_status = f"{c.PASTEL_GREEN}READY TO CLAIM{c.RESET}"
        else:
            right_status = f"{c.PASTEL_GREEN}SPAWNED{c.RESET} {c.PASTEL_YELLOW}(claim in {wait_right}s){c.RESET} {c.PASTEL_GRAY}(+{jitter_right}s jitter){c.RESET}"
    else:
        right_status = f"{c.WHITE}{ts_to_str(right_ts)}{c.RESET} {c.PASTEL_YELLOW}in {format_duration(orig_wait_right)}{c.RESET} {c.PASTEL_GRAY}(+{jitter_right}s jitter){c.RESET}"

    if left_ts <= right_ts:
        next_target = "Chest #1"
        next_orig_ts = left_ts
        next_orig_wait = orig_wait_left
        next_jitter = jitter_left
        next_wait_sec = wait_left
    else:
        next_target = "Chest #2"
        next_orig_ts = right_ts
        next_orig_wait = orig_wait_right
        next_jitter = jitter_right
        next_wait_sec = wait_right

    if next_orig_wait == 0:
        if next_wait_sec == 0:
            next_target_val = f"{c.BOLD}{c.WHITE}{next_target}{c.RESET} {c.PASTEL_GREEN}[READY TO CLAIM]{c.RESET}"
        else:
            next_target_val = f"{c.BOLD}{c.WHITE}{next_target}{c.RESET} {c.PASTEL_YELLOW}spawned (claim in {next_wait_sec}s){c.RESET} {c.PASTEL_GRAY}(+{next_jitter}s jitter){c.RESET}"
    else:
        next_target_val = f"{c.BOLD}{c.WHITE}{next_target}{c.RESET} {c.WHITE}{ts_to_str(next_orig_ts)}{c.RESET} {c.PASTEL_YELLOW}in {format_duration(next_orig_wait)}{c.RESET} {c.PASTEL_GRAY}(+{next_jitter}s jitter){c.RESET}"

    bar_width = 18
    if total_duration > 0 and next_orig_wait <= total_duration:
        elapsed = max(0, total_duration - next_orig_wait)
        pct = min(1.0, elapsed / max(1, total_duration))
    else:
        pct = 0.0
    filled = int(pct * bar_width)
    bar_str = f"{c.PASTEL_CYAN}{'━' * filled}{c.PASTEL_GRAY}{'─' * (bar_width - filled)}{c.RESET} {c.BOLD}{c.PASTEL_YELLOW}{int(pct * 100)}%{c.RESET}"

    sep = f"{c.BORDER_GRAY}│{c.RESET}"

    def row(bar_color: str, label: str, value: str, width: int = 12) -> str:
        pad = " " * max(0, width - len(label))
        return f"  {bar_color}▌{c.RESET} {c.WHITE}{label}{pad}{c.RESET} {sep} {value}"

    lines = []
    lines.append("")

    # Block 1: User & Account (Pastel Cyan bar)
    lines.append(row(c.PASTEL_CYAN, "Player", f"{c.BOLD}{c.WHITE}{nickname}{c.RESET}"))
    lines.append(row(c.PASTEL_CYAN, "Balance", f"{c.BOLD}{c.PASTEL_GREEN}{balance:,} clicks{c.RESET}"))
    lines.append(row(c.PASTEL_CYAN, "Total Stats", f"{c.WHITE}{total_clicks:,} clicks total{c.RESET} {c.PASTEL_GRAY}│ Spent {total_consume:,}{c.RESET}"))
    ot = collection_state["owned_total"]
    at = max(1, collection_state["atlas_total"])
    if ot > 0:
        ob = collection_state["owned_by_type"]
        ab = collection_state["atlas_by_type"]
        col_pct = ot * 100 / at
        col_str = (
            f"{c.BOLD}{c.PASTEL_YELLOW}{ot}/{at}{c.RESET} {c.PASTEL_GRAY}({col_pct:.1f}%) │ "
            f"Char {ob.get('Character', 0)}/{ab.get('Character', 260)} · "
            f"Acc {ob.get('Accessory', 0)}/{ab.get('Accessory', 135)} · "
            f"Emote {ob.get('Emote', 0)}/{ab.get('Emote', 504)}{c.RESET}"
        )
        lines.append(row(c.PASTEL_CYAN, "Collection", col_str))
    lines.append("")

    # Block 2: Engine, Idle Farm & Session (Pastel Pink bar)
    mode_disp = claim_mode or ("CDP Native-Click (Pet Synced)" if app_running else "Headless API Mode")
    lines.append(row(c.PASTEL_PINK, "Mode", f"{c.BOLD}{c.PASTEL_GREEN}{mode_disp}{c.RESET}"))
    farm_col = c.PASTEL_GREEN if idle_farm_enabled else c.PASTEL_GRAY
    lines.append(row(c.PASTEL_PINK, "Idle Farm", f"{farm_col}{idle_farm_status}{c.RESET}"))
    with _stats_lock:
        sc_tot = session_stats["chests_claimed"]
        sc_new = session_stats["new_count"]
        sc_dup = session_stats["dup_count"]
        sc_frm = session_stats["farmed_clicks"]
    sess_str = (
        f"{c.WHITE}Chests: {sc_tot}{c.RESET} "
        f"{c.PASTEL_GRAY}({c.PASTEL_GREEN}{sc_new} NEW{c.PASTEL_GRAY} · {sc_dup} DUP) │ "
        f"Farmed: {c.PASTEL_CYAN}+{sc_frm:,} clicks{c.RESET}"
    )
    lines.append(row(c.PASTEL_PINK, "Session", sess_str))
    lines.append(row(c.PASTEL_PINK, "State", f"{c.BOLD}{c.PASTEL_CYAN}{current_action}{c.RESET}"))
    lines.append(row(c.PASTEL_PINK, "Jitter", f"{c.WHITE}{min_delay}s - {max_delay}s{c.RESET} {c.PASTEL_GRAY}│ Min Interval: {interval}s{c.RESET}"))
    lines.append("")

    # Block 3: Chest Schedule & Progress (Pastel Blue bar)
    lines.append(row(c.PASTEL_BLUE, "Next Target", next_target_val))
    lines.append(row(c.PASTEL_BLUE, "Progress", bar_str))
    lines.append(row(c.PASTEL_BLUE, "Chest #1", left_status))
    lines.append(row(c.PASTEL_BLUE, "Chest #2", right_status))

    # Block 4: Recent Claim Activity (Pastel Green bar)
    if last_claim_msg:
        lines.append("")
        lines.append(row(c.PASTEL_GREEN, "Last Claim", f"{c.BOLD}{c.PASTEL_GREEN}{last_claim_msg}{c.RESET}"))

    lines.append("")

    # Footer: Color dots palette & status
    dots = (
        f"\033[38;5;117m● \033[38;5;110m● \033[38;5;75m● \033[38;5;153m● "
        f"\033[38;5;255m● \033[38;5;218m● \033[38;5;212m●{c.RESET}"
    )
    lines.append(f"  {dots}")
    lines.append(f"  \033[38;5;117mc( ^. .^){c.RESET} \033[38;5;218m« Zani is working hard diligently! (˶ᵔ ᵕ ᵔ˶){c.RESET}")
    lines.append(f"  {c.PASTEL_GRAY}[F] Idle Farm   [T] Stats   [S] Settings   [L] Logs   [H] Hide   [Q] Quit{c.RESET}")
    lines.append("")

    return lines


def clear_terminal():

    if os.name == "nt":
        os.system("cls")
    else:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def redraw_screen(
    nickname: str,
    balance: int,
    total_clicks: int,
    total_consume: int,
    left_ts: int,
    right_ts: int,
    now_ts: int,
    app_running: bool,
    token_str: str = "",
    cid_str: str = "",
    has_webhook: bool = False,
    last_claim_msg: str = "",
    in_place: bool = False,
    delays: dict = None,
    current_action: str = "Monitoring",
    min_delay: int = 5,
    max_delay: int = 60,
    interval: int = 10,
    total_duration: int = 1800,
    claim_mode: str = "",
):

    global is_window_visible
    if not is_window_visible:
        return

    lines = []
    lines.extend(build_banner_lines())
    lines.extend(build_dashboard_lines(
        nickname=nickname,
        balance=balance,
        total_clicks=total_clicks,
        total_consume=total_consume,
        left_ts=left_ts,
        right_ts=right_ts,
        now_ts=now_ts,
        app_running=app_running,
        token_str=token_str,
        cid_str=cid_str,
        has_webhook=has_webhook,
        delays=delays,
        current_action=current_action,
        min_delay=min_delay,
        max_delay=max_delay,
        interval=interval,
        total_duration=total_duration,
        last_claim_msg=last_claim_msg,
        claim_mode=claim_mode,
    ))

    if in_place:
        cleared = "\n".join(l + "\033[K" for l in lines)
        sys.stdout.write("\033[H" + cleared + "\033[J\n")
    else:
        clear_terminal()
        sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


_instance_mutex_handle = None


def acquire_single_instance_mutex() -> bool:
    """Prevent multiple instances of WuwaTappo AutoClaim from running concurrently."""
    global _instance_mutex_handle
    if os.name != "nt":
        return True
    try:
        h = kernel32.CreateMutexW(None, False, "Local\\WuwaTappoAutoClaim_SingleInstance")
        last_err = kernel32.GetLastError()
        if not h:
            return True
        if last_err == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(h)
            return False
        _instance_mutex_handle = h
        return True
    except Exception:
        return True


def merge_chest_ts(*candidates) -> int:
    """Monotonically pick the newest valid chest timestamp (> 0) so cached /user/me responses never roll timers backward."""
    valid = []
    for x in candidates:
        try:
            v = int(x or 0)
            if v > 0:
                valid.append(v)
        except Exception:
            pass
    return max(valid) if valid else 0


def main():
    global pet_sync_enabled, is_claiming_chest
    load_lifetime_stats()
    cli_args = parse_cli_args()
    if cli_args and getattr(cli_args, "no_sync", False):
        pet_sync_enabled = False

    if cli_args and cli_args.status_only:
        token, cid, webhook_url, token_src, cid_src, show_window_cfg, min_delay_sec, max_delay_sec, min_chest_interval_sec = load_config(cli_args)
        client = WuwaTappoClient(token, cid)
        try:
            user = client.get_user_info()
            server_time = client.get_server_time()
            bag_items = client.get_bag_list()
            refresh_collection_state(client, bag_items=bag_items, fetch_atlas=True)
        except Exception as e:
            print(f"Error fetching account info: {e}")
            sys.exit(1)

        nickname = user.get("nickname", "User")
        total_clicks = user.get("total_click_count", 0)
        total_consume = user.get("total_click_consume", 0)
        left_ts = user.get("left_treasure_chest", 0)
        right_ts = user.get("right_treasure_chest", 0)
        pet_on = is_app_running()
        cdp_on = is_cdp_ready() if pet_on else False
        mode_str = "CDP Native-Click (Ready)" if (pet_on and cdp_on) else ("Pet Open (CDP Not Attached Yet)" if pet_on else "Headless API Mode")

        lines = build_banner_lines()
        lines.extend(build_dashboard_lines(
            nickname=nickname,
            balance=total_clicks - total_consume,
            total_clicks=total_clicks,
            total_consume=total_consume,
            left_ts=left_ts,
            right_ts=right_ts,
            now_ts=server_time,
            app_running=pet_on,
            cid_str=f"{cid[:6]}...{cid[-6:]}",
            current_action="Snapshot Check (--status)",
            min_delay=min_delay_sec,
            max_delay=max_delay_sec,
            interval=min_chest_interval_sec,
            claim_mode=mode_str,
        ))
        print("\n".join(lines))
        if bag_items:
            counts = {}
            qty_sum = 0
            for it in bag_items:
                if not isinstance(it, dict):
                    continue
                t = classify_asset_type(it.get("asset_type", ""), it.get("asset_name", ""))
                counts[t] = counts.get(t, 0) + 1
                qty_sum += int(it.get("quantity") or it.get("num") or 1)
            summary = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
            print(f"  Bag Summary: {len(bag_items)} unique ({summary}) | Total quantity: {qty_sum}\n")
        sys.exit(0)

    if pet_sync_enabled and is_app_running() and not is_cdp_ready():
        ensure_admin()
    if not acquire_single_instance_mutex():
        print(f"  {Color.YELLOW}[!] {PROJECT_NAME} is already running in another window or System Tray.{Color.RESET}")
        logger.warning("Duplicate instance detected — exiting cleanly.")
        time.sleep(2.5)
        sys.exit(0)

    init_terminal()
    render_banner()
    restart_pet_if_needed()
    print(f"  {Color.GRAY}[*] Loading token and account info...{Color.RESET}", flush=True)



    token, cid, webhook_url, token_src, cid_src, show_window_cfg, min_delay_sec, max_delay_sec, min_chest_interval_sec = load_config(cli_args)
    client = WuwaTappoClient(token, cid)

    init_tray()
    if os.name == "nt":
        threading.Thread(target=window_monitor_loop, daemon=True).start()
        threading.Thread(target=console_input_loop, daemon=True).start()
        threading.Thread(target=idle_farm_worker, daemon=True).start()

    token_str = f"{token[:8]}...{token[-8:]}"
    cid_str = f"{cid[:6]}...{cid[-6:]}"
    has_webhook = bool(webhook_url)

    time_offset = 0.0
    last_clock_sync_mono = 0.0
    last_wall_clock = time.time()

    def sync_server_clock(silent: bool = False):
        nonlocal time_offset, last_clock_sync_mono
        try:
            srv_ts = client.get_server_time()
            time_offset = srv_ts - (time.time() * 1000)
            last_clock_sync_mono = time.monotonic()
            logger.info(f"Server time synchronized. Offset: {time_offset:+.1f}ms")
        except Exception as e:
            if not silent:
                print(f"  {Color.RED}[-] Clock sync failed: {e}{Color.RESET}")
            logger.warning(f"Clock sync failed: {e}")

    print(f"  {Color.GRAY}[*] Synchronizing clock with Kuro server...{Color.RESET}")
    sync_server_clock(silent=False)

    def current_server_ts():
        return time.time() * 1000 + time_offset

    try:
        user = client.get_user_info()
    except Exception as e:
        print(f"  {Color.RED}[-] Failed to load user account: {e}{Color.RESET}")
        logger.error(f"Failed to load user account: {e}")
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\nPress Enter to exit...")
        except Exception:
            pass
        return

    nickname = user.get("nickname", "User")
    total_clicks = user.get("total_click_count", 0)
    total_consume = user.get("total_click_consume", 0)
    live_balance_ref["total_clicks"] = total_clicks
    live_balance_ref["total_consume"] = total_consume
    left_ts = merge_chest_ts(user.get("left_treasure_chest", 0))
    right_ts = merge_chest_ts(user.get("right_treasure_chest", 0))
    try:
        refresh_collection_state(client, fetch_atlas=True)
    except Exception:
        pass

    chest_count = 0
    last_claim_msg = ""
    app_running = is_app_running()
    def get_chest_delay():
        return random.randint(min_delay_sec, max_delay_sec)

    chest_delays = {
        "left": get_chest_delay(),
        "right": get_chest_delay()
    }
    current_action = "Monitoring"
    last_chest_open_total = {"left": 1800, "right": 1800}

    _mode_cache = {"ts": 0.0, "app_on": app_running, "cdp_on": False, "label": "Headless API Mode"}

    def refresh_mode_status(force: bool = False):
        nonlocal app_running
        now_m = time.monotonic()
        if not force and (now_m - _mode_cache["ts"]) < 10.0:
            app_running = _mode_cache["app_on"]
            return _mode_cache["app_on"], _mode_cache["cdp_on"], _mode_cache["label"]

        pet_on = is_app_running()
        cdp_on = False
        if pet_on:
            cdp_on = is_cdp_ready() and bool(find_cdp_main_target())
            if cdp_on:
                lbl = "CDP Native-Click (Pet Synced)"
            elif pet_sync_enabled:
                lbl = "Paused (Pet Open w/o CDP)"
            else:
                lbl = "Direct API (--no-sync)"
        else:
            lbl = "Headless API Mode"

        app_running = pet_on
        _mode_cache.update({"ts": now_m, "app_on": pet_on, "cdp_on": cdp_on, "label": lbl})
        return pet_on, cdp_on, lbl

    def update_view(override_claim_msg=None, in_place=False, action=None, total_duration=1800, force_mode=False):
        nonlocal current_action, last_claim_msg
        if is_setting_active:
            return
        if action:
            current_action = action
        if override_claim_msg is not None:
            last_claim_msg = override_claim_msg

        disp_clicks = max(total_clicks, live_balance_ref["total_clicks"])
        disp_consume = max(total_consume, live_balance_ref["total_consume"])
        _, _, mode_lbl = refresh_mode_status(force=force_mode)
        redraw_screen(
            nickname=nickname,
            balance=disp_clicks - disp_consume,
            total_clicks=disp_clicks,
            total_consume=disp_consume,
            left_ts=left_ts,
            right_ts=right_ts,
            now_ts=current_server_ts(),
            app_running=app_running,
            token_str=token_str,
            cid_str=cid_str,
            has_webhook=has_webhook,
            last_claim_msg=last_claim_msg,
            in_place=in_place,
            delays=chest_delays,
            current_action=current_action,
            min_delay=min_delay_sec,
            max_delay=max_delay_sec,
            interval=min_chest_interval_sec,
            total_duration=total_duration,
            claim_mode=mode_lbl,
        )

    global global_update_view_fn
    global_update_view_fn = update_view

    update_view(action="Started Auto Claim", force_mode=True)

    if not show_window_cfg:
        hide_window(notify_user=False)

    claim_failures = {"left": 0, "right": 0}
    not_ready_waits = {"left": 0, "right": 0}
    last_claim_monotonic = 0.0
    last_cdp_retry_monotonic = 0.0

    while running_flag:
        try:
            # Detect PC Sleep/Hibernate wake or 60-minute periodic clock drift re-sync
            wall_now = time.time()
            if abs((wall_now - last_wall_clock) - 1.0) > 15.0 or (time.monotonic() - last_clock_sync_mono) > 3600:
                sync_server_clock(silent=True)
            last_wall_clock = wall_now

            now = current_server_ts()
            target_left_ts = left_ts + (chest_delays["left"] * 1000)
            target_right_ts = right_ts + (chest_delays["right"] * 1000)

            left_due = now >= target_left_ts
            right_due = now >= target_right_ts
            chest_to_open = "left" if left_due else ("right" if right_due else None)

            if chest_to_open:
                # Enforce minimum interval between ANY two claims without freezing the dashboard
                if last_claim_monotonic > 0:
                    elapsed_since_claim = time.monotonic() - last_claim_monotonic
                    if elapsed_since_claim < min_chest_interval_sec:
                        rem_int = int(min_chest_interval_sec - elapsed_since_claim) + 1
                        update_view(in_place=True, action=f"Interval cooldown ({rem_int}s)")
                        time.sleep(1)
                        continue

                sys.stdout.write("\r" + " " * 75 + "\r")
                sys.stdout.flush()

                app_running, cdp_active, _ = refresh_mode_status(force=True)

                # Guard: if Pet is open without CDP and sync is enabled, do NOT send raw API claims behind Pet's back
                if app_running and not cdp_active and pet_sync_enabled:
                    if is_admin() and (time.monotonic() - last_cdp_retry_monotonic) > 30:
                        last_cdp_retry_monotonic = time.monotonic()
                        update_view(action="Re-attaching CDP to Wuwa Tappo...", force_mode=True)
                        restart_pet_if_needed()
                        app_running, cdp_active, _ = refresh_mode_status(force=True)
                    if not cdp_active:
                        update_view(in_place=True, action="Paused: Pet open w/o CDP (run as Admin or close Pet)")
                        time.sleep(3)
                        continue

                try:
                    u = client.get_user_info()
                    if client.token != token:
                        token = client.token
                        token_str = f"{token[:8]}...{token[-8:]} - Auto-Refreshed"
                    total_clicks = u.get("total_click_count", total_clicks)
                    total_consume = u.get("total_click_consume", total_consume)
                    left_ts = merge_chest_ts(left_ts, u.get("left_treasure_chest"))
                    right_ts = merge_chest_ts(right_ts, u.get("right_treasure_chest"))

                    now = current_server_ts()
                    target_left_ts = left_ts + (chest_delays["left"] * 1000)
                    target_right_ts = right_ts + (chest_delays["right"] * 1000)
                    left_due = now >= target_left_ts
                    right_due = now >= target_right_ts
                    if not left_due and not right_due:
                        update_view()
                        time.sleep(1)
                        continue
                    chest_to_open = "left" if left_due else "right"
                except Exception as e:
                    logger.debug(f"Pre-claim user info sync failed: {e}")

                if cdp_active:
                    # Smart readiness check & anti-starvation before clicking
                    pet_state = get_pet_live_state()
                    if pet_state:
                        st = pet_state.get("store") or {}
                        if st:
                            left_ts = merge_chest_ts(left_ts, st.get("leftTs"))
                            right_ts = merge_chest_ts(right_ts, st.get("rightTs"))
                            if st.get("totalClickCount", 0) < CHEST_COST:
                                update_view(in_place=True, action=f"Low balance ({st.get('totalClickCount', 0):,} < {CHEST_COST:,} clicks)")
                                time.sleep(5)
                                continue

                        l_ready = bool(pet_state.get("leftReady"))
                        r_ready = bool(pet_state.get("rightReady"))
                        now = current_server_ts()
                        left_due = now >= (left_ts + chest_delays["left"] * 1000)
                        right_due = now >= (right_ts + chest_delays["right"] * 1000)

                        if left_due and l_ready:
                            chest_to_open = "left"
                        elif right_due and r_ready:
                            chest_to_open = "right"
                        else:
                            pending_side = "left" if left_due else ("right" if right_due else None)
                            if not pending_side:
                                update_view()
                                time.sleep(1)
                                continue
                            not_ready_waits[pending_side] = not_ready_waits.get(pending_side, 0) + 1
                            p_label = "Chest #1" if pending_side == "left" else "Chest #2"
                            if not_ready_waits[pending_side] >= 5:
                                chest_delays[pending_side] += 15
                                not_ready_waits[pending_side] = 0
                                logger.debug(f"[CDP] {p_label} button not visible after 5 checks — adding +15s delay buffer.")
                            update_view(in_place=True, action=f"Waiting for {p_label} button in Pet UI...")
                            time.sleep(2)
                            continue

                # Snapshot bag before opening to identify [NEW] vs [DUP xN]
                is_claiming_chest = True
                bag_before = {}
                try:
                    bag_before = build_bag_snapshot(client.get_bag_list())
                except Exception as e:
                    logger.debug(f"Pre-claim bag snapshot failed: {e}")

                place_name = "Chest #1" if chest_to_open == "left" else "Chest #2"
                res = None
                claim_mode_used = "CDP Native-Click" if cdp_active else "Headless API"

                try:
                    if cdp_active:
                        update_view(action=f"Clicking {place_name} in Pet UI (CDP)...")
                        logger.info(f"[CDP] Triggering native in-app click on {place_name}...")
                        cdp_res = claim_chest_via_cdp(chest_to_open, timeout_sec=10.0)
                        st_code = cdp_res.get("status")

                        if st_code == "not_ready":
                            logger.debug(f"[CDP] {place_name} button not ready yet ({cdp_res.get('detail')}). Waiting...")
                            update_view(in_place=True, action=f"Waiting for {place_name} button in Pet UI...")
                            time.sleep(2)
                            continue
                        elif st_code == "ok":
                            res = cdp_res.get("response", {"code": 0, "data": {}})
                        elif st_code == "clicked_no_body":
                            # Button was clicked; verify via bags/list & user/me diff after short wait
                            time.sleep(2.0)
                            bag_after_tmp = {}
                            try:
                                bag_after_tmp = build_bag_snapshot(client.get_bag_list())
                                u2 = client.get_user_info()
                                total_clicks = u2.get("total_click_count", total_clicks)
                                total_consume = u2.get("total_click_consume", total_consume)
                                left_ts = merge_chest_ts(left_ts, u2.get("left_treasure_chest"))
                                right_ts = merge_chest_ts(right_ts, u2.get("right_treasure_chest"))
                            except Exception:
                                pass
                            diff_item = None
                            for k, curr in bag_after_tmp.items():
                                prev = bag_before.get(k)
                                if prev is None or curr.get("quantity", 0) > prev.get("quantity", 0):
                                    diff_item = curr
                                    break
                            if diff_item:
                                res = {
                                    "code": 0,
                                    "data": {
                                        "asset_id": diff_item.get("asset_id"),
                                        "asset_name": diff_item.get("asset_name", "Unknown"),
                                        "asset_type": diff_item.get("asset_type", ""),
                                        "rarity_type": diff_item.get("rarity_type", "common"),
                                        "click_consume": CHEST_COST,
                                        "left_next_time": left_ts,
                                        "right_next_time": right_ts,
                                    },
                                }
                            else:
                                res = {"code": -1, "message": cdp_res.get("detail", "CDP click sent, no response captured")}
                        elif st_code == "api_error":
                            res = cdp_res.get("response") or {"code": -1, "message": cdp_res.get("detail", "CDP API error")}
                        else:
                            res = {"code": -1, "message": f"CDP error: {cdp_res.get('detail', 'unknown')}"}
                    else:
                        # Clean Headless API Mode (Pet is closed or --no-sync): NEVER fabricate fake clicks!
                        current_balance = total_clicks - total_consume
                        if current_balance < CHEST_COST:
                            update_view(in_place=True, action=f"Low balance ({current_balance:,} < {CHEST_COST:,} clicks) - Waiting")
                            time.sleep(10)
                            continue

                        target_click = total_clicks
                        update_view(action=f"Claiming {place_name} (API)...")
                        sys.stdout.write(f"\r  {Color.YELLOW}[*] Claiming {place_name}...{' ' * 35}\r")
                        sys.stdout.flush()
                        logger.info(f"[API] Claiming {place_name} - Clicks: {target_click:,}...")

                        res = client.open_chest(chest_to_open, target_click)
                        if client.token != token:
                            token = client.token
                            token_str = f"{token[:8]}...{token[-8:]} - Auto-Refreshed"
                finally:
                    is_claiming_chest = False

                if res and res.get("code") == 0:
                    claim_failures[chest_to_open] = 0
                    not_ready_waits[chest_to_open] = 0
                    last_claim_monotonic = time.monotonic()
                    chest_count += 1
                    data = res.get("data", {}) or {}
                    asset_id = data.get("asset_id")
                    asset = data.get("asset_name", "Unknown")
                    asset_type_raw = data.get("asset_type", "")
                    rarity = data.get("rarity_type", "common")
                    consume = data.get("click_consume", CHEST_COST)

                    # Monotonically merge next chest timestamps so cached /user/me never rolls timers backward
                    left_ts = merge_chest_ts(left_ts, data.get("left_next_time"))
                    right_ts = merge_chest_ts(right_ts, data.get("right_next_time"))

                    bag_after = {}
                    try:
                        u_after = client.get_user_info()
                        total_clicks = u_after.get("total_click_count", total_clicks)
                        total_consume = max(total_consume + consume, u_after.get("total_click_consume", 0))
                        left_ts = merge_chest_ts(left_ts, u_after.get("left_treasure_chest"))
                        right_ts = merge_chest_ts(right_ts, u_after.get("right_treasure_chest"))
                    except Exception:
                        total_consume += consume

                    try:
                        bag_raw = client.get_bag_list()
                        bag_after = build_bag_snapshot(bag_raw)
                        refresh_collection_state(client, bag_items=bag_raw, fetch_atlas=False)
                    except Exception:
                        pass

                    live_balance_ref["total_clicks"] = max(live_balance_ref["total_clicks"], total_clicks)
                    live_balance_ref["total_consume"] = max(live_balance_ref["total_consume"], total_consume)

                    is_new, new_qty = evaluate_bag_reward(bag_before, asset_id=asset_id, asset_name=asset, bag_after=bag_after)
                    next_ts_val = left_ts if chest_to_open == "left" else right_ts
                    next_cd = int(next_ts_val - current_server_ts()) // 1000
                    last_chest_open_total[chest_to_open] = max(1, next_cd)
                    chest_delays[chest_to_open] = get_chest_delay()

                    item_type = classify_asset_type(asset_type_raw, asset)
                    rarity_str = rarity.capitalize() if rarity else "Common"
                    record_claim_stat(place_name, asset, item_type, rarity_str, is_new, new_qty)
                    status_badge = "[NEW]" if is_new is True else (f"[DUP x{new_qty}]" if is_new is False and new_qty else ("[DUP]" if is_new is False else "[CLAIMED]"))
                    last_claim_msg = f"{place_name} {status_badge} {item_type}: {asset} ({rarity_str})"

                    logger.info(
                        f"SUCCESS #{chest_count} [{claim_mode_used}]: Claimed {place_name}! "
                        f"{status_badge} {item_type} '{asset}' ({rarity_str}, id={asset_id}) | "
                        f"Balance: {total_clicks - total_consume:,} | Raw: {data}"
                    )

                    send_discord_webhook(
                        webhook_url=webhook_url,
                        nickname=nickname,
                        place=chest_to_open,
                        asset_name=asset,
                        rarity=rarity,
                        balance=total_clicks - total_consume,
                        left_wait_sec=max(0, int((left_ts - current_server_ts()) / 1000)),
                        right_wait_sec=max(0, int((right_ts - current_server_ts()) / 1000)),
                        asset_type=asset_type_raw,
                        is_new=is_new,
                        quantity=new_qty,
                        claim_mode=claim_mode_used,
                    )

                    update_view(override_claim_msg=last_claim_msg, action=f"Claimed {place_name} ({claim_mode_used})", total_duration=last_chest_open_total[chest_to_open], force_mode=True)
                    time.sleep(1)
                    continue
                else:
                    err_msg = (res or {}).get("message", str(res))
                    sys.stdout.write(f"\r  {Color.RED}[!] Failed to claim {place_name}: {err_msg}{' ' * 10}\r")
                    sys.stdout.flush()
                    logger.warning(f"Failed to claim {place_name} [{claim_mode_used}]: {err_msg}")
                    claim_failures[chest_to_open] = claim_failures.get(chest_to_open, 0) + 1
                    try:
                        u = client.get_user_info()
                        if client.token != token:
                            token = client.token
                            token_str = f"{token[:8]}...{token[-8:]} - Auto-Refreshed"
                        total_clicks = u.get("total_click_count", total_clicks)
                        total_consume = u.get("total_click_consume", total_consume)
                        left_ts = merge_chest_ts(left_ts, u.get("left_treasure_chest"))
                        right_ts = merge_chest_ts(right_ts, u.get("right_treasure_chest"))
                    except Exception:
                        pass

                    if claim_failures[chest_to_open] >= 3:
                        logger.warning(f"Repeated failures for {place_name} - Adding 30s cooldown buffer...")
                        if chest_to_open == "left":
                            left_ts = max(left_ts, int(now + 30000))
                        else:
                            right_ts = max(right_ts, int(now + 30000))
                        chest_delays[chest_to_open] = get_chest_delay()
                        claim_failures[chest_to_open] = 0

                    update_view(force_mode=True)
                    time.sleep(2)
                    continue

            wait_left = max(0, int((target_left_ts - now) / 1000))
            wait_right = max(0, int((target_right_ts - now) / 1000))
            next_wait = min(wait_left, wait_right)
            next_name = "Chest #1" if wait_left <= wait_right else "Chest #2"
            chest_key = "left" if wait_left <= wait_right else "right"
            total_duration = last_chest_open_total.get(chest_key, 1800)

            if next_wait > 0:
                update_view(in_place=True, action=f"Waiting for {next_name}", total_duration=total_duration)
                time.sleep(1)
                continue

            sys.stdout.write("\r" + " " * 75 + "\r")
            sys.stdout.flush()

        except KeyboardInterrupt:
            print(f"\n\n  {Color.YELLOW}[*] Auto Claim stopped by user. Goodbye!{Color.RESET}\n")
            logger.info("Program stopped by user.")
            break
        except Exception as e:
            print(f"\n  {Color.RED}[!] Unexpected error: {e}{Color.RESET}")
            logger.error(f"Unexpected exception: {e}", exc_info=True)
            time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_app_exit()
