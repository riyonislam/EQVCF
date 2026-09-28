import os
import re
import sys
import json
import time
import shutil
import argparse
import subprocess
import concurrent.futures
from threading import Lock

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
lock = Lock()

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

def run_nlm_cmd(cmd_args, profile_name, cookie_str, base_url, timeout=120, lang_code=None):
    nlm_bin = find_nlm_binary()
    env = os.environ.copy()
    env["NOTEBOOKLM_COOKIES"] = cookie_str
    env["NOTEBOOKLM_BASE_URL"] = base_url
    if lang_code:
        env["NOTEBOOKLM_HL"] = lang_code
    full_cmd = [nlm_bin, "--profile", profile_name] + cmd_args
    try:
        proc = subprocess.run(full_cmd, capture_output=True, text=True, env=env, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

def setup_profile_auth(profile_name, cookie_str):
    nlm_bin = find_nlm_binary()
    cookie_temp = f"/tmp/{profile_name}_cookie.txt"
    with open(cookie_temp, "w", encoding="utf-8") as f:
        f.write(cookie_str.strip())
    hosts = ["https://notebook.google.com", "https://notebooklm.google.com"]
    for host in hosts:
        env = os.environ.copy()
        env["NOTEBOOKLM_BASE_URL"] = host
        cmd = [nlm_bin, "--profile", profile_name, "login", "--manual", "--file", cookie_temp]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
            if p.returncode == 0 or "saved" in p.stdout.lower() or "logged in" in p.stdout.lower():
                return host
        except Exception:
            pass
    return hosts[0]

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

class AccountState:
    def __init__(self, idx, cookie):
        self.idx = idx
        self.cookie = cookie
        self.profile = f"acc_{idx}"
        self.base_url = "https://notebook.google.com"
        self.active_tasks = 0
        self.total_completed = 0
        self.is_ready = False
        self.is_exhausted = False
        self.assigned_tasks = []

class AudioTask:
    def __init__(self, lang_item):
        self.lang = lang_item
        self.name = lang_item["name"]
        self.folder = lang_item["folder"]
        self.code = lang_item["code"]
        self.prompt_lang = lang_item["prompt_lang"]
        self.status = "PENDING"  # PENDING, TRIGGERING, GENERATING, COMPLETED, FAILED
        self.assigned_acc = None
        self.nb_id = None
        self.art_id = None
        self.start_time = 0
        self.tried_accounts = set()

def trigger_task_generation(task, acc, source_type, source_data):
    nb_title = f"Pod_{int(time.time())}_{random.randint(100, 999)}"
    code, out, err = run_nlm_cmd(["notebook", "create", nb_title, "--json"], acc.profile, acc.cookie, acc.base_url, timeout=90, lang_code=task.code)
    nb_id = extract_notebook_id(out)
    if not nb_id:
        code, out, err = run_nlm_cmd(["notebook", "create", nb_title], acc.profile, acc.cookie, acc.base_url, timeout=90, lang_code=task.code)
        nb_id = extract_notebook_id(out)

    if not nb_id:
        return False, f"Notebook create error: {err or out}"

    task.nb_id = nb_id

    # Add Source
    if source_type == "links":
        for u in source_data:
            run_nlm_cmd(["source", "add", nb_id, "--url", u, "--wait"], acc.profile, acc.cookie, acc.base_url, timeout=90, lang_code=task.code)
    elif source_type == "book":
        s_code, s_out, s_err = run_nlm_cmd(["source", "add", nb_id, "--file", source_data, "--wait"], acc.profile, acc.cookie, acc.base_url, timeout=120, lang_code=task.code)
        if s_code != 0:
            run_nlm_cmd(["notebook", "delete", nb_id, "--confirm"], acc.profile, acc.cookie, acc.base_url, timeout=30)
            return False, f"Source add error: {s_err or s_out}"

    # Trigger Audio
    custom_prompt = f"Generate the podcast entirely in {task.prompt_lang}."
    a_code, a_out, a_err = run_nlm_cmd([
        "audio", "create", nb_id,
        "--language", task.code,
        "--focus", custom_prompt,
        "--confirm"
    ], acc.profile, acc.cookie, acc.base_url, timeout=90, lang_code=task.code)

    if a_code != 0:
        run_nlm_cmd(["notebook", "delete", nb_id, "--confirm"], acc.profile, acc.cookie, acc.base_url, timeout=30)
        return False, f"Audio trigger error: {a_err or a_out}"

    return True, None

def print_live_tracker(accounts, tasks):
    completed = sum(1 for t in tasks if t.status == "COMPLETED")
    generating = sum(1 for t in tasks if t.status == "GENERATING")
    pending = sum(1 for t in tasks if t.status == "PENDING")
    
    print("\n" + "=" * 80)
    print(f"📊 [LIVE TRACKER] মোট: {len(tasks)} | সম্পন্ন: {completed} ✓ | জেনারেট হচ্ছে: {generating} ⏳ | বাকি: {pending}")
    print("-" * 80)
    for acc in accounts:
        if not acc.assigned_tasks:
            continue
        items_str = []
        for t in acc.assigned_tasks:
            elapsed = int(time.time() - t.start_time) // 60 if t.start_time else 0
            if t.status == "COMPLETED":
                items_str.append(f"{t.name}: [✓ সম্পন্ন]")
            elif t.status == "GENERATING":
                items_str.append(f"{t.name}: [⏳ জেনারেট হচ্ছে ({elapsed}মি)]")
            elif t.status == "TRIGGERING":
                items_str.append(f"{t.name}: [নোটবুক তৈরি হচ্ছে]")
            elif t.status == "FAILED":
                items_str.append(f"{t.name}: [✗ ফেইল]")
        print(f"👤 Account #{acc.idx + 1} ({len(items_str)}/3): " + ", ".join(items_str))
    print("=" * 80 + "\n")

def main():
    parser = argparse.ArgumentParser(description="NotebookLM Parallel Multi-Account Audio Engine")
    parser.add_argument("--workspace", default="./Workspace", help="Workspace path")
    parser.add_argument("--channels_config", default="channels_config.json", help="Path to channels_config.json")
    args = parser.parse_args()

    workspace_dir = os.path.abspath(args.workspace)
    channels_cfg = load_channels_config(args.channels_config)
    raw_cookies_json = os.environ.get("COOKIES_POOL_JSON")

    if not raw_cookies_json:
        print("Error: GitHub Secrets-এ 'COOKIES_POOL_JSON' সেট করা নেই।")
        sys.exit(1)

    account_cookies = parse_cookies_pool(raw_cookies_json)
    if not account_cookies:
        print("Error: COOKIES_POOL_JSON থেকে ভ্যালিড অ্যাকাউন্ট লোড করা যায়নি।")
        sys.exit(1)

    source_type, source_data = detect_sources(workspace_dir)
    if not source_type:
        print("Error: Link.txt বা Book.txt কিছুই পাওয়া যায়নি।")
        sys.exit(1)

    # ফিল্টারিং: বন্ধ থাকা চ্যানেল এবং এক্সিস্টিং অডিও বাদ দেওয়া
    tasks_to_run = []
    for lang in LANGUAGE_CONFIG:
        if not is_channel_enabled(lang, channels_cfg):
            continue
        folder_path = os.path.join(workspace_dir, lang["folder"])
        if folder_has_audio(folder_path):
            print(f"[SKIP] '{lang['name']}' ({lang['folder']})-এ অডিও আগে থেকেই আছে। স্কিপ করা হলো।")
            continue
        tasks_to_run.append(AudioTask(lang))

    if not tasks_to_run:
        print("[+] কোনো নতুন অডিও জেনারেট করার প্রয়োজন নেই। সব তৈরি আছে!")
        sys.exit(0)

    print(f"\n[+] মোট {len(tasks_to_run)} টি ভাষার অডিও প্যারালালে তৈরি করতে হবে।")
    print(f"[+] পুলে মোট {len(account_cookies)} টি অ্যাকাউন্ট প্রস্তুত রয়েছে।")

    accounts = [AccountState(i, c) for i, c in enumerate(account_cookies)]

    # অ্যাকাউন্টগুলোর অথেন্টিকেশন সেশন তৈরি (একবার করে নেওয়া)
    print("\n[*] অ্যাকাউন্টগুলোর সেশন প্রস্তুত করা হচ্ছে...")
    for acc in accounts:
        acc.base_url = setup_profile_auth(acc.profile, acc.cookie)
        acc.is_ready = True
    print("[+] সকল অ্যাকাউন্টের সেশন প্রস্তুত!\n")

    start_engine_time = time.time()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

    while True:
        # ১. পেন্ডিং টাস্কগুলোকে এভেইলেবল অ্যাকাউন্টে অ্যাসাইন করা (প্রতি অ্যাকাউন্টে ৩টি করে)
        with lock:
            pending_tasks = [t for t in tasks_to_run if t.status == "PENDING"]
            for task in pending_tasks:
                available_acc = None
                for acc in accounts:
                    # যে অ্যাকাউন্টে ৩টির কম সক্রিয় টাস্ক আছে এবং মোট ৩টির বেশি সফল হয়নি
                    if acc.is_ready and not acc.is_exhausted and acc.active_tasks < 3:
                        if acc.idx not in task.tried_accounts:
                            available_acc = acc
                            break

                if available_acc:
                    task.status = "TRIGGERING"
                    task.assigned_acc = available_acc
                    task.tried_accounts.add(available_acc.idx)
                    available_acc.active_tasks += 1
                    if task not in available_acc.assigned_tasks:
                        available_acc.assigned_tasks.append(task)

                    def launch_job(t=task, a=available_acc):
                        success, err = trigger_task_generation(t, a, source_type, source_data)
                        with lock:
                            if success:
                                t.status = "GENERATING"
                                t.start_time = time.time()
                            else:
                                print(f"[-] {t.name} অ্যাকাউন্টে ফেইল করেছে: {err}। পরবর্তী অ্যাকাউন্টে পাঠানো হবে।")
                                t.status = "PENDING"
                                a.active_tasks -= 1
                                if t in a.assigned_tasks:
                                    a.assigned_tasks.remove(t)

                    executor.submit(launch_job)

        # ২. লাইভ ট্র্যাকিং বোর্ড প্রিন্ট
        print_live_tracker(accounts, tasks_to_run)

        # ৩. সব টাস্ক সম্পন্ন হয়েছে কি না চেক
        all_done = all(t.status in ("COMPLETED", "FAILED") for t in tasks_to_run)
        if all_done:
            break

        # ৪. জেনারেটিং টাস্কগুলোর স্ট্যাটাস পোলিং
        with lock:
            active_gen_tasks = [t for t in tasks_to_run if t.status == "GENERATING"]

        for task in active_gen_tasks:
            acc = task.assigned_acc
            st_code, st_out, st_err = run_nlm_cmd(["studio", "status", task.nb_id, "--json"], acc.profile, acc.cookie, acc.base_url, timeout=45, lang_code=task.code)
            status, art_id = check_audio_status(st_out)
            if status == "unknown":
                st_code, st_out, st_err = run_nlm_cmd(["studio", "status", task.nb_id], acc.profile, acc.cookie, acc.base_url, timeout=45, lang_code=task.code)
                status, art_id = check_audio_status(st_out)

            if status == "completed":
                print(f"[✓ প্রস্তুত!] {task.name} এর অডিও রেডি হয়েছে। ডাউনলোড হচ্ছে...")
                temp_audio = f"/tmp/nlm_{task.folder}_{int(time.time())}.m4a"
                dl_cmd = ["download", "audio", task.nb_id, "--output", temp_audio]
                if art_id:
                    dl_cmd = ["download", "audio", task.nb_id, "--id", art_id, "--output", temp_audio]

                run_nlm_cmd(dl_cmd, acc.profile, acc.cookie, acc.base_url, timeout=120, lang_code=task.code)
                target_folder = os.path.join(workspace_dir, task.folder)
                os.makedirs(target_folder, exist_ok=True)
                target_mp3 = os.path.join(target_folder, "podcast_audio.mp3")

                # FFMPEG দিয়ে রূপান্তর
                subprocess.run(["ffmpeg", "-y", "-i", temp_audio, "-c:a", "libmp3lame", "-q:a", "2", target_mp3], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if not os.path.exists(target_mp3):
                    shutil.copyfile(temp_audio, os.path.join(target_folder, "podcast_audio.m4a"))

                # রিমোট নোটবুক মুছে ফেলা
                run_nlm_cmd(["notebook", "delete", task.nb_id, "--confirm"], acc.profile, acc.cookie, acc.base_url, timeout=30, lang_code=task.code)

                with lock:
                    task.status = "COMPLETED"
                    acc.active_tasks -= 1
                    acc.total_completed += 1
                    if acc.total_completed >= 3:
                        acc.is_exhausted = True

            elif status == "failed" or (time.time() - task.start_time > 1500):  # ২৫ মিনিট টাইমআউট
                print(f"[!] {task.name} জেনারেশন ফেইল করেছে বা সময় পার হয়েছে। নোটবুক ক্লিয়ার করে অন্য অ্যাকাউন্টে পাঠানো হচ্ছে...")
                run_nlm_cmd(["notebook", "delete", task.nb_id, "--confirm"], acc.profile, acc.cookie, acc.base_url, timeout=30, lang_code=task.code)
                with lock:
                    task.status = "PENDING"
                    acc.active_tasks -= 1
                    if task in acc.assigned_tasks:
                        acc.assigned_tasks.remove(t)

        time.sleep(45)

    executor.shutdown(wait=True)
    total_elapsed = int(time.time() - start_engine_time) // 60
    print("\n" + "=" * 80)
    print(f"🎉 সকল ভাষার অডিও সফলভাবে তৈরি হয়েছে! মোট সময় লেগেছে: {total_elapsed} মিনিট।")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
