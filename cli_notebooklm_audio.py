import os
import re
import sys
import json
import time
import shutil
import argparse
import subprocess

LANGUAGE_CONFIG = [
    {"name": "Deutsch", "folder": "Deutsch", "code": "de", "prompt_lang": "German", "channel": "NextRead Deutsch"},
    {"name": "English", "folder": "English", "code": "en", "prompt_lang": "English", "channel": "NextRead English"},
    {"name": "Español", "folder": "Español", "code": "es", "prompt_lang": "Spanish", "channel": "NextRead Español"},
    {"name": "Français", "folder": "Français", "code": "fr", "prompt_lang": "French", "channel": "NextRead Français"},
    {"name": "Indonesia", "folder": "Indonesia", "code": "id", "prompt_lang": "Indonesian", "channel": "NextRead Indonesia"},
    {"name": "Italiano", "folder": "Italiano", "code": "it", "prompt_lang": "Italian", "channel": "NextRead Italiano"},
    {"name": "Nederlands", "folder": "Nederlands", "code": "nl", "prompt_lang": "Dutch", "channel": "NextRead Nederlands"},
    {"name": "Norsk", "folder": "Norsk", "code": "no", "prompt_lang": "Norwegian", "channel": "NextRead Norsk"},
    {"name": "Polski", "folder": "Polski", "code": "pl", "prompt_lang": "Polish", "channel": "NextRead Polski"},
    {"name": "Português", "folder": "Português", "code": "pt", "prompt_lang": "Portuguese", "channel": "NextRead Português"},
    {"name": "Tiếng Việt", "folder": "Tiếng Việt", "code": "vi", "prompt_lang": "Vietnamese", "channel": "NextRead Tiếng Việt"},
    {"name": "Türkçe", "folder": "Türkçe", "code": "tr", "prompt_lang": "Turkish", "channel": "NextRead Türkçe"},
    {"name": "ελληνικά", "folder": "ελληνικά", "code": "el", "prompt_lang": "Greek", "channel": "NextRead ελληνικά"},
    {"name": "Русский", "folder": "Русский", "code": "ru", "prompt_lang": "Russian", "channel": "NextRead Русский"},
    {"name": "العربية", "folder": "العربية", "code": "ar", "prompt_lang": "Arabic", "channel": "NextRead العربية"},
    {"name": "हिन्दी", "folder": "हिन्दी", "code": "hi", "prompt_lang": "Hindi", "channel": "NextRead हिन्दी"},
    {"name": "বাংলা", "folder": "বাংলা", "code": "bn", "prompt_lang": "Bengali", "channel": "NextRead বাংলা"},
    {"name": "한국어", "folder": "한국어", "code": "ko", "prompt_lang": "Korean", "channel": "NextRead 한국어"},
    {"name": "中文", "folder": "中文", "code": "zh-TW", "prompt_lang": "Traditional Chinese", "channel": "NextRead 中文 (繁體)"},
    {"name": "日本語", "folder": "日本語", "code": "ja", "prompt_lang": "Japanese", "channel": "NextRead 日本語"},
]

AUDIO_EXTENSIONS = ('.mp3', '.m4a', '.wav', '.ogg', '.flac', '.aac')

def load_channels_config(config_path="channels_config.json"):
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def is_channel_enabled(lang_item, channels_cfg):
    if not channels_cfg:
        return True
    ch_name = lang_item.get("channel", "")
    folder_name = lang_item.get("folder", "")
    if ch_name in channels_cfg:
        return bool(channels_cfg[ch_name])
    if folder_name in channels_cfg:
        return bool(channels_cfg[folder_name])
    return True

def find_nlm_binary():
    nlm_path = shutil.which("nlm")
    if nlm_path: return nlm_path
    candidate = os.path.join(os.path.dirname(sys.executable), "nlm")
    if os.path.exists(candidate): return candidate
    return "nlm"

def parse_cookies_pool(raw_json_str):
    if not raw_json_str: return []
    try:
        data = json.loads(raw_json_str.strip())
    except Exception:
        return []
    accounts = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                c = item.strip().replace("\n", " ")
                if c: accounts.append(c)
            elif isinstance(item, dict):
                c = item.get("cookies") or item.get("cookie")
                if c and isinstance(c, str):
                    accounts.append(c.strip().replace("\n", " "))
    return accounts

def folder_has_audio(folder_path):
    if not os.path.exists(folder_path): return False
    for f in os.listdir(folder_path):
        if f.lower().endswith(AUDIO_EXTENSIONS):
            return True
    return False

def detect_sources(workspace_dir):
    for c in ["Link.txt", "link.txt", "LINK.TXT"]:
        p = os.path.join(workspace_dir, c)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                urls = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
            if urls: return "links", urls
    for c in ["Book.txt", "book.txt", "BOOK.TXT"]:
        p = os.path.join(workspace_dir, c)
        if os.path.exists(p): return "book", p
    return None, None

def run_nlm(cmd_args, cookie_str, timeout=60, lang_code=None):
    nlm_bin = find_nlm_binary()
    env = os.environ.copy()
    env["NOTEBOOKLM_COOKIES"] = cookie_str
    env["NOTEBOOKLM_BASE_URL"] = "https://notebook.google.com"
    if lang_code:
        env["NOTEBOOKLM_HL"] = lang_code
    full_cmd = [nlm_bin] + cmd_args
    try:
        proc = subprocess.run(
            full_cmd, 
            capture_output=True, 
            text=True, 
            env=env, 
            timeout=timeout,
            stdin=subprocess.DEVNULL
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        return -1, "", str(e)

def extract_notebook_id(output):
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            for k in ("id", "notebook_id", "notebookId"):
                if k in data: return data[k]
    except Exception:
        pass
    m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", output)
    if m: return m.group(1)
    m = re.search(r"(?:Created notebook|notebook[:\s]+)\s*([a-zA-Z0-9_-]{10,})", output, re.IGNORECASE)
    if m: return m.group(1)
    return None

def check_audio_status(output):
    try:
        data = json.loads(output)
        items = data if isinstance(data, list) else data.get("artifacts", [])
        for item in items:
            atype = str(item.get("type", "")).lower()
            if "audio" in atype or "podcast" in atype:
                status = str(item.get("status", "")).lower()
                art_id = item.get("id") or item.get("artifact_id")
                return status, art_id
    except Exception:
        pass
    for line in output.splitlines():
        lower_line = line.lower()
        if "audio" in lower_line or "podcast" in lower_line:
            art_id_match = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", line)
            art_id = art_id_match.group(1) if art_id_match else None
            if "completed" in lower_line or "✓" in line:
                return "completed", art_id
            elif "in_progress" in lower_line or "pending" in lower_line:
                return "in_progress", art_id
            elif "failed" in lower_line or "error" in lower_line or "✗" in line:
                return "failed", art_id
    return "unknown", None

class Task:
    def __init__(self, lang_item):
        self.lang = lang_item
        self.name = lang_item["name"]
        self.folder = lang_item["folder"]
        self.code = lang_item["code"]
        self.prompt_lang = lang_item["prompt_lang"]
        self.status = "PENDING"  # PENDING, GENERATING, COMPLETED, FAILED
        self.acc_idx = None
        self.nb_id = None
        self.art_id = None
        self.start_time = 0
        self.tried_accounts = set()

def print_tracker(tasks, total_accounts):
    completed = sum(1 for t in tasks if t.status == "COMPLETED")
    generating = sum(1 for t in tasks if t.status == "GENERATING")
    pending = sum(1 for t in tasks if t.status == "PENDING")
    
    print("\n" + "=" * 80)
    print(f"📊 [LIVE TRACKER] মোট: {len(tasks)} | সম্পন্ন: {completed} ✓ | ক্লাউডে জেনারেট হচ্ছে: {generating} ⏳ | বাকি: {pending}")
    print("-" * 80)
    acc_map = {}
    for t in tasks:
        if t.acc_idx is not None:
            acc_map.setdefault(t.acc_idx, []).append(t)
            
    for acc_idx in sorted(acc_map.keys()):
        items = []
        for t in acc_map[acc_idx]:
            if t.status == "COMPLETED":
                items.append(f"{t.name}: [✓ সম্পন্ন]")
            elif t.status == "GENERATING":
                elapsed = int(time.time() - t.start_time) // 60
                items.append(f"{t.name}: [⏳ জেনারেট হচ্ছে ({elapsed}মি)]")
            elif t.status == "FAILED":
                items.append(f"{t.name}: [✗ ফেইল]")
        print(f"👤 Account #{acc_idx + 1} ({len(items)}/3): " + ", ".join(items))
    print("=" * 80 + "\n")

def main():
    parser = argparse.ArgumentParser(description="NotebookLM Smart Batch Audio Engine")
    parser.add_argument("--workspace", default="./Workspace", help="Workspace path")
    parser.add_argument("--channels_config", default="channels_config.json", help="Path to channels_config.json")
    args = parser.parse_args()

    workspace_dir = os.path.abspath(args.workspace)
    channels_cfg = load_channels_config(args.channels_config)
    raw_cookies_json = os.environ.get("COOKIES_POOL_JSON")

    if not raw_cookies_json:
        print("Error: GitHub Secrets-এ 'COOKIES_POOL_JSON' পাওয়া যায়নি।")
        sys.exit(1)

    accounts = parse_cookies_pool(raw_cookies_json)
    if not accounts:
        print("Error: COOKIES_POOL_JSON থেকে অ্যাকাউন্ট লোড করা যায়নি।")
        sys.exit(1)

    source_type, source_data = detect_sources(workspace_dir)
    if not source_type:
        print("Error: Link.txt বা Book.txt কিছুই পাওয়া যায়নি।")
        sys.exit(1)

    tasks = []
    for lang in LANGUAGE_CONFIG:
        if not is_channel_enabled(lang, channels_cfg):
            continue
        folder_path = os.path.join(workspace_dir, lang["folder"])
        if folder_has_audio(folder_path):
            print(f"[SKIP] '{lang['name']}' ফোল্ডারে অডিও আগে থেকেই আছে।")
            continue
        tasks.append(Task(lang))

    if not tasks:
        print("[+] কোনো নতুন অডিও জেনারেট করার প্রয়োজন নেই।")
        sys.exit(0)

    print(f"\n[+] মোট {len(tasks)} টি ভাষার অডিও স্বয়ংক্রিয়ভাবে তৈরি শুরু হচ্ছে।")
    print(f"[+] পুলে মোট {len(accounts)} টি অ্যাকাউন্ট সক্রিয় রয়েছে।\n")

    # -------------------------------------------------------------
    # ধাপ ১: দ্রুত সবগুলো অডিও ক্লাউডে ট্রিগার করা (মাত্র ২ মিনিট)
    # -------------------------------------------------------------
    print(">>> ধাপ ১: সব কয়টি ভাষার অডিও গুগলের ক্লাউডে ট্রিগার করা হচ্ছে... <<<")
    acc_usage = [0] * len(accounts)

    for task in tasks:
        # ৩টির কম ব্যবহৃত অ্যাকাউন্ট খুঁজে বের করা
        assigned = False
        for acc_idx in range(len(accounts)):
            if acc_usage[acc_idx] < 3 and acc_idx not in task.tried_accounts:
                cookie = accounts[acc_idx]
                nb_title = f"Pod_{task.folder}_{int(time.time())}"
                print(f"[*] Account #{acc_idx + 1} দিয়ে '{task.name}' ট্রিগার করা হচ্ছে...")
                
                # নোটবুক তৈরি
                c_code, c_out, c_err = run_nlm(["notebook", "create", nb_title, "--json"], cookie, timeout=45, lang_code=task.code)
                nb_id = extract_notebook_id(c_out)
                if not nb_id:
                    c_code, c_out, c_err = run_nlm(["notebook", "create", nb_title], cookie, timeout=45, lang_code=task.code)
                    nb_id = extract_notebook_id(c_out)

                if not nb_id:
                    print(f"[-] Account #{acc_idx + 1}-এ নোটবুক তৈরি ব্যর্থ। পরবর্তী অ্যাকাউন্টে পাঠানো হচ্ছে...")
                    task.tried_accounts.add(acc_idx)
                    continue

                # সোর্স যোগ করা
                if source_type == "links":
                    for u in source_data:
                        run_nlm(["source", "add", nb_id, "--url", u, "--wait"], cookie, timeout=60, lang_code=task.code)
                elif source_type == "book":
                    run_nlm(["source", "add", nb_id, "--file", source_data, "--wait"], cookie, timeout=90, lang_code=task.code)

                # অডিও জেনারেশন স্টার্ট
                custom_prompt = f"Generate the podcast entirely in {task.prompt_lang}."
                a_code, a_out, a_err = run_nlm([
                    "audio", "create", nb_id,
                    "--language", task.code,
                    "--focus", custom_prompt,
                    "--confirm"
                ], cookie, timeout=45, lang_code=task.code)

                if a_code == 0:
                    task.status = "GENERATING"
                    task.nb_id = nb_id
                    task.acc_idx = acc_idx
                    task.start_time = time.time()
                    acc_usage[acc_idx] += 1
                    assigned = True
                    print(f"[✓ সফল ট্রিগার] {task.name} এর অডিও ব্যাকগ্রাউন্ডে জেনারেট হওয়া শুরু হয়েছে!")
                    break
                else:
                    run_nlm(["notebook", "delete", nb_id, "--confirm"], cookie, timeout=30)
                    task.tried_accounts.add(acc_idx)

        if not assigned:
            print(f"[!] সতর্কতা: {task.name} কোনো অ্যাকাউন্টে শুরু করা যায়নি।")

    print("\n[+] সকল ভাষার অডিও গুগলের ক্লাউড সার্ভারে একযোগে তৈরি হচ্ছে!\n")

    # -------------------------------------------------------------
    # ধাপ ২: লাইভ ট্র্যাকিং এবং রেডি হওয়া মাত্র ডাউনলোড (১০-১২ মিনিট)
    # -------------------------------------------------------------
    print(">>> ধাপ ২: ক্লাউড স্ট্যাটাস ট্র্যাকিং ও ডাউনলোড পর্ব শুরু... <<<")
    start_wait_time = time.time()

    while True:
        print_tracker(tasks, len(accounts))

        active_tasks = [t for t in tasks if t.status == "GENERATING"]
        if not active_tasks:
            break

        for task in active_tasks:
            cookie = accounts[task.acc_idx]
            st_code, st_out, st_err = run_nlm(["studio", "status", task.nb_id, "--json"], cookie, timeout=30, lang_code=task.code)
            status, art_id = check_audio_status(st_out)
            if status == "unknown":
                st_code, st_out, st_err = run_nlm(["studio", "status", task.nb_id], cookie, timeout=30, lang_code=task.code)
                status, art_id = check_audio_status(st_out)

            if status == "completed":
                print(f"\n[🎉 প্রস্তুত!] {task.name} এর অডিও সম্পূর্ণ হয়েছে। ডাউনলোড হচ্ছে...")
                temp_audio = f"/tmp/nlm_{task.folder}_{int(time.time())}.m4a"
                dl_cmd = ["download", "audio", task.nb_id, "--output", temp_audio]
                if art_id:
                    dl_cmd = ["download", "audio", task.nb_id, "--id", art_id, "--output", temp_audio]

                run_nlm(dl_cmd, cookie, timeout=120, lang_code=task.code)
                
                target_folder = os.path.join(workspace_dir, task.folder)
                os.makedirs(target_folder, exist_ok=True)
                target_mp3 = os.path.join(target_folder, "podcast_audio.mp3")

                # FFMPEG রূপান্তর
                subprocess.run(["ffmpeg", "-y", "-i", temp_audio, "-c:a", "libmp3lame", "-q:a", "2", target_mp3], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if not os.path.exists(target_mp3):
                    shutil.copyfile(temp_audio, os.path.join(target_folder, "podcast_audio.m4a"))

                # গুগল ক্লাউড থেকে নোটবুক ডিলিট
                run_nlm(["notebook", "delete", task.nb_id, "--confirm"], cookie, timeout=30)
                task.status = "COMPLETED"
                print(f"[✓ সেভ সম্পন্ন] {task.name} এর অডিও ফোল্ডারে সেভ হয়েছে!\n")

            elif status == "failed" or (time.time() - task.start_time > 1200): # ২০ মিনিট পার হলে
                print(f"\n[!] {task.name} ব্যর্থ হয়েছে বা সময় পার হয়েছে। নোটবুক ক্লিয়ার করা হচ্ছে...")
                run_nlm(["notebook", "delete", task.nb_id, "--confirm"], cookie, timeout=30)
                task.status = "FAILED"

        time.sleep(45)

    total_time = int(time.time() - start_wait_time) // 60
    print("\n" + "=" * 80)
    print(f"🎉 সকল অডিও জেনারেশন পর্ব সমাপ্ত! মোট সময় লেগেছে: {total_time} মিনিট।")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
