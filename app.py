

import argparse
import asyncio
import atexit
import base64
import ctypes
import datetime
import hashlib
import json
import logging
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


PROJECT_NAME = "Wuwa Tappo Auto Claim"
APP_VERSION = "1.0.0"


if getattr(sys, "frozen", False):
    WORKSPACE_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", WORKSPACE_DIR)
else:
    WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = WORKSPACE_DIR

CONFIG_FILE = os.path.join(WORKSPACE_DIR, "config.json")
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



logger = logging.getLogger("AutoClaim")
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
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
    """Sets Zani icon for Console window HWND and sets explicit AppUserModelID."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WuwaTappo.AutoClaim.Zani.1.0.0")
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
                "Wuwa Tappo Auto Claim is running in System Tray.\nClick icon to restore window.",
                "Wuwa Tappo Auto Claim",
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
                tray_icon.notify(msg, "Wuwa Tappo Auto Claim")
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


def init_tray():

    global tray_icon
    menu = pystray.Menu(
        pystray.MenuItem(
            lambda item: "Hide Window" if is_window_visible else "Show Window",
            toggle_window,
            default=True,
        ),
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
        "Wuwa Tappo Auto Claim",
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
    if is_setting_active:
        return
    is_setting_active = True
    c = Color
    try:
        sys.stdout.write("\033[?25h\n")
        while is_setting_active:
            print(f"\n  {c.BOLD}{c.PASTEL_YELLOW}─── [S] QUICK SETTINGS MENU ───{c.RESET}")
            print(f"  {c.PASTEL_CYAN}[1]{c.RESET} Min Jitter Delay       : {c.WHITE}{min_delay_sec}s{c.RESET}")
            print(f"  {c.PASTEL_CYAN}[2]{c.RESET} Max Jitter Delay       : {c.WHITE}{max_delay_sec}s{c.RESET}")
            print(f"  {c.PASTEL_CYAN}[3]{c.RESET} Min Chest Interval     : {c.WHITE}{min_chest_interval_sec}s{c.RESET}")
            webhook_disp = f"{webhook_url[:22]}...{webhook_url[-8:]}" if webhook_url else "(Disabled)"
            print(f"  {c.PASTEL_CYAN}[4]{c.RESET} Discord Webhook URL    : {c.WHITE}{webhook_disp}{c.RESET}")
            game_disp = custom_game_path if custom_game_path else "(Auto-Detect)"
            print(f"  {c.PASTEL_CYAN}[5]{c.RESET} Custom Game Path       : {c.WHITE}{game_disp}{c.RESET}")
            print(f"  {c.PASTEL_CYAN}[0]{c.RESET} Save & Return to Dashboard\n")

            choice = input(f"  {c.BOLD}Select option to edit [0-5]: {c.RESET}").strip()
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
            elif choice in ("0", "", "q", "Q"):
                chest_delays["left"] = random.randint(min_delay_sec, max_delay_sec)
                chest_delays["right"] = random.randint(min_delay_sec, max_delay_sec)
                print(f"\n  {c.PASTEL_GREEN}[+] Settings saved. Returning to dashboard...{c.RESET}")
                time.sleep(0.7)
                break
            else:
                print(f"  {c.PASTEL_YELLOW}[!] Invalid choice. Please enter 0 to 5.{c.RESET}")
    except Exception as e:
        logger.debug(f"Prompt settings error: {e}")
    finally:
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
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
                if ch in (b'h', b'H', b'm', b'M'):
                    hide_window(notify_user=True)
                elif ch in (b's', b'S'):
                    prompt_settings()
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

    global webhook_url, custom_game_path
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


def send_discord_webhook(
    webhook_url: str,
    nickname: str,
    place: str,
    asset_name: str,
    rarity: str,
    balance: int,
    left_wait_sec: int,
    right_wait_sec: int,
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

    embed = {
        "title": f"{place_label} Claimed Successfully!",
        "color": embed_color,
        "fields": [
            {"name": "Player", "value": nickname, "inline": True},
            {"name": "Chest", "value": place_label, "inline": True},
            {"name": "Rarity", "value": rarity.capitalize() if rarity else "Common", "inline": True},
            {"name": "Reward Item", "value": f"`{asset_name}`", "inline": True},
            {"name": "Balance", "value": f"{balance:,} clicks", "inline": True},
            {
                "name": "Next Cooldowns",
                "value": f"Left: `{format_duration(left_wait_sec)}` | Right: `{format_duration(right_wait_sec)}`",
                "inline": False,
            },
        ],
        "footer": {
            "text": f"{PROJECT_NAME} - {PROJECT_AUTHOR}",
        },
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    if image_url:
        embed["thumbnail"] = {"url": image_url}

    payload = {
        "username": f"Wuwa Tappo Auto Claim (Desktop v{APP_VERSION})",
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

        try:
            return self.session.request(method, url, **kwargs)
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
                    tray_icon.notify("Session token was refreshed automatically.", "Wuwa Tappo Auto Claim")
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


def ensure_wuwa_tappo_running():
    c = Color
    if is_app_running():
        print(f"  {c.PASTEL_GREEN}[+] Wuwa Tappo is currently running.{c.RESET}")
        logger.info("Wuwa Tappo is currently running.")
        return

    app_exe = find_wuwa_tappo_exe()
    if app_exe and os.path.exists(app_exe):
        print(f"  {c.PASTEL_CYAN}[*] Starting Wuwa Tappo ({app_exe})...{c.RESET}")
        logger.info(f"Starting Wuwa Tappo: {app_exe}")
        try:
            cwd = os.path.dirname(app_exe)
            ctypes.windll.shell32.ShellExecuteW(None, "open", app_exe, None, cwd, 1)
            for _ in range(6):
                time.sleep(1)
                if is_app_running():
                    print(f"  {c.PASTEL_GREEN}[+] Wuwa Tappo started successfully!{c.RESET}\n")
                    logger.info("Wuwa Tappo started successfully via ShellExecuteW.")
                    break
        except Exception as e:
            print(f"  {c.PASTEL_YELLOW}[!] Could not launch Wuwa Tappo: {e}{c.RESET}")
            logger.debug(f"Could not launch Wuwa Tappo: {e}")


def cleanup_app_exit():
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
    if cid_str:
        lines.append(row(c.PASTEL_CYAN, "CID", f"{c.WHITE}{cid_str}{c.RESET}"))
    lines.append("")

    # Block 2: Engine & Timing Config (Pastel Pink bar)
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

    # Footer: Color dots palette & mascot
    dots = (
        f"\033[38;5;117m● \033[38;5;110m● \033[38;5;75m● \033[38;5;153m● "
        f"\033[38;5;255m● \033[38;5;218m● \033[38;5;212m●{c.RESET}"
    )
    lines.append(f"  {dots}")
    lines.append(f"  \033[38;5;117mc( ^. .^){c.RESET} \033[38;5;218m« Zani is working hard diligently! (˶ᵔ ᵕ ᵔ˶){c.RESET}")
    lines.append(f"  {c.PASTEL_GRAY}[H] Hide to Tray    [S] Settings    [Q] Quit{c.RESET}")
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
    ))

    content = "\n".join(lines)
    if in_place:
        sys.stdout.write("\033[H" + content + "   \n")
    else:
        clear_terminal()
        sys.stdout.write(content + "\n")
    sys.stdout.flush()


def main():
    cli_args = parse_cli_args()

    if cli_args and cli_args.status_only:
        token, cid, webhook_url, token_src, cid_src, show_window_cfg, min_delay_sec, max_delay_sec, min_chest_interval_sec = load_config(cli_args)
        client = WuwaTappoClient(token, cid)
        try:
            user = client.get_user_info()
            server_time = client.get_server_time()
        except Exception as e:
            print(f"Error fetching account info: {e}")
            sys.exit(1)

        nickname = user.get("nickname", "User")
        total_clicks = user.get("total_click_count", 0)
        total_consume = user.get("total_click_consume", 0)
        left_ts = user.get("left_treasure_chest", 0)
        right_ts = user.get("right_treasure_chest", 0)

        lines = build_banner_lines()
        lines.extend(build_dashboard_lines(
            nickname=nickname,
            balance=total_clicks - total_consume,
            total_clicks=total_clicks,
            total_consume=total_consume,
            left_ts=left_ts,
            right_ts=right_ts,
            now_ts=server_time,
            app_running=is_app_running(),
            cid_str=f"{cid[:6]}...{cid[-6:]}",
            current_action="Snapshot Check (--status)",
            min_delay=min_delay_sec,
            max_delay=max_delay_sec,
            interval=min_chest_interval_sec,
        ))
        print("\n".join(lines))
        sys.exit(0)

    init_terminal()
    render_banner()
    ensure_wuwa_tappo_running()

    token, cid, webhook_url, token_src, cid_src, show_window_cfg, min_delay_sec, max_delay_sec, min_chest_interval_sec = load_config(cli_args)
    client = WuwaTappoClient(token, cid)

    init_tray()
    if os.name == "nt":
        threading.Thread(target=window_monitor_loop, daemon=True).start()
        threading.Thread(target=console_input_loop, daemon=True).start()

    token_str = f"{token[:8]}...{token[-8:]}"
    cid_str = f"{cid[:6]}...{cid[-6:]}"
    has_webhook = bool(webhook_url)

    print(f"  {Color.GRAY}[*] Synchronizing clock with Kuro server...{Color.RESET}")
    try:
        server_time_init = client.get_server_time()
        local_time_init = time.time() * 1000
        time_offset = server_time_init - local_time_init
        logger.info(f"Server time synchronized. Offset: {time_offset:+.1f}ms")
    except Exception as e:
        print(f"  {Color.RED}[-] Clock sync failed: {e}{Color.RESET}")
        logger.error(f"Clock sync failed: {e}")
        time_offset = 0

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
    left_ts = user.get("left_treasure_chest", 0)
    right_ts = user.get("right_treasure_chest", 0)

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

    def update_view(override_claim_msg=None, in_place=False, action=None, total_duration=1800):
        nonlocal current_action, last_claim_msg
        if is_setting_active:
            return
        if action:
            current_action = action
        if override_claim_msg is not None:
            last_claim_msg = override_claim_msg

        redraw_screen(
            nickname=nickname,
            balance=total_clicks - total_consume,
            total_clicks=total_clicks,
            total_consume=total_consume,
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
        )

    global global_update_view_fn
    global_update_view_fn = update_view

    update_view(action="Started Auto Claim")

    if not show_window_cfg:
        hide_window(notify_user=False)

    claim_failures = {"left": 0, "right": 0}

    while running_flag:
        try:
            now = current_server_ts()
            left_cd = max(0, int((left_ts - now) / 1000))
            right_cd = max(0, int((right_ts - now) / 1000))

            target_left_ts = left_ts + (chest_delays["left"] * 1000)
            target_right_ts = right_ts + (chest_delays["right"] * 1000)

            chest_to_open = None
            if now >= target_left_ts:
                chest_to_open = "left"
            elif now >= target_right_ts:
                chest_to_open = "right"

            if chest_to_open:
                sys.stdout.write("\r" + " " * 75 + "\r")
                sys.stdout.flush()

                app_running = is_app_running()

                try:
                    u = client.get_user_info()
                    if client.token != token:
                        token = client.token
                        token_str = f"{token[:8]}...{token[-8:]} - Auto-Refreshed"
                    total_clicks = u.get("total_click_count", total_clicks)
                    total_consume = u.get("total_click_consume", total_consume)
                    left_ts = u.get("left_treasure_chest", left_ts)
                    right_ts = u.get("right_treasure_chest", right_ts)

                    now = current_server_ts()
                    if chest_to_open == "left" and left_ts > now:
                        update_view()
                        time.sleep(1)
                        continue
                    if chest_to_open == "right" and right_ts > now:
                        update_view()
                        time.sleep(1)
                        continue
                except Exception as e:
                    logger.debug(f"Pre-claim user info sync failed: {e}")

                click_gain = CLICK_GAIN_PER_CHEST + random.randint(15, 95)
                target_click = total_clicks + click_gain
                min_needed = (total_consume + CHEST_COST) + MIN_BALANCE_MAINTAIN
                if target_click < min_needed:
                    target_click = min_needed

                place_name = "Chest #1" if chest_to_open == "left" else "Chest #2"
                update_view(action=f"Claiming {place_name} - +{click_gain} clicks")
                sys.stdout.write(f"\r  {Color.YELLOW}[*] Claiming {place_name}...{' ' * 35}\r")
                sys.stdout.flush()
                logger.info(f"Claiming {place_name} - Clicks: {target_click:,}...")

                res = client.open_chest(chest_to_open, target_click)
                if client.token != token:
                    token = client.token
                    token_str = f"{token[:8]}...{token[-8:]} - Auto-Refreshed"

                if res.get("code") == 0:
                    claim_failures[chest_to_open] = 0
                    chest_count += 1
                    data = res.get("data", {})
                    asset = data.get("asset_name", "Unknown")
                    rarity = data.get("rarity_type", "common")
                    consume = data.get("click_consume", CHEST_COST)

                    total_clicks = target_click
                    total_consume += consume

                    new_left = data.get("left_next_time", 0)
                    new_right = data.get("right_next_time", 0)
                    if new_left > 0:
                        left_ts = new_left
                    if new_right > 0:
                        right_ts = new_right

                    next_cd = int((new_left if chest_to_open == "left" else new_right) - current_server_ts()) // 1000
                    last_chest_open_total[chest_to_open] = max(1, next_cd)
                    chest_delays[chest_to_open] = get_chest_delay()
                    other_chest = "right" if chest_to_open == "left" else "left"
                    other_ts = right_ts if chest_to_open == "left" else left_ts
                    this_target = (left_ts if chest_to_open == "left" else right_ts) + (chest_delays[chest_to_open] * 1000)
                    other_target = other_ts + (chest_delays[other_chest] * 1000)
                    diff = abs(this_target - other_target) // 1000
                    if diff < min_chest_interval_sec:
                        chest_delays[other_chest] += int(min_chest_interval_sec - diff)
                    time.sleep(min_chest_interval_sec)

                    last_claim_msg = f"{place_name} (+{consume:,} clicks) -> Balance: {total_clicks - total_consume:,} clicks"

                    logger.info(
                        f"SUCCESS #{chest_count}: Claimed {place_name}! "
                        f"New balance: {total_clicks - total_consume:,}"
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
                    )

                    update_view(override_claim_msg=last_claim_msg, action=f"Successfully claimed {place_name}!", total_duration=last_chest_open_total[chest_to_open])
                    time.sleep(1)
                    continue
                else:
                    err_msg = res.get("message", str(res))
                    sys.stdout.write(f"\r  {Color.RED}[!] Failed to claim {place_name}: {err_msg}{' ' * 10}\r")
                    sys.stdout.flush()
                    logger.warning(f"Failed to claim {place_name}: {err_msg}")
                    claim_failures[chest_to_open] = claim_failures.get(chest_to_open, 0) + 1
                    try:
                        u = client.get_user_info()
                        if client.token != token:
                            token = client.token
                            token_str = f"{token[:8]}...{token[-8:]} - Auto-Refreshed"
                        total_clicks = u.get("total_click_count", total_clicks)
                        total_consume = u.get("total_click_consume", total_consume)
                        left_ts = u.get("left_treasure_chest", left_ts)
                        right_ts = u.get("right_treasure_chest", right_ts)
                    except Exception:
                        pass

                    if claim_failures[chest_to_open] >= 3:
                        logger.warning(f"Repeated failures for {place_name} - Adding 30s cooldown buffer...")
                        if chest_to_open == "left":
                            left_ts = now + 30000
                        else:
                            right_ts = now + 30000
                        chest_delays[chest_to_open] = get_chest_delay()
                        claim_failures[chest_to_open] = 0

                    update_view()
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
