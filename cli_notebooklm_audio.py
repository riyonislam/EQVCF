import os
import re
import sys
import json
import time
import random
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
        except Exception as e:
            print(f"Warning: Could not read {config_path}: {e}")
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
    if nlm_path:
        return nlm_path
    candidate = os.path.join(os.path.dirname(sys.executable), "nlm")
    if os.path.exists(candidate):
        return candidate
    return "nlm"

def setup_account_session(cookies):
    """
    কুকি দিয়ে nlm login --manual রান করে সেশন লোকাল প্রোফাইলে সেভ করে নেয়।
    নতুন ও পুরোনো (notebook.google.com / notebooklm.google.com) উভয় ডোমেইন সাপোর্ট করে।
    """
    nlm_bin = find_nlm_binary()
    cookie_temp_path = "/tmp/nlm_active_cookie.txt"
    with open(cookie_temp_path, "w", encoding="utf-8") as f:
        f.write(cookies.strip())

    base_hosts = ["https://notebook.google.com", "https://notebooklm.google.com"]
    for host in base_hosts:
        env = os.environ.copy()
        env["NOTEBOOKLM_BASE_URL"] = host
        cmd = [nlm_bin, "login", "--manual", "--file", cookie_temp_path]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
            if proc.returncode == 0 or "saved" in proc.stdout.lower() or "logged in" in proc.stdout.lower():
                print(f"[+] অথেন্টিকেশন সফল হয়েছে! হোস্ট: {host}")
                return host
        except Exception:
            pass

    # ফলব্যাক হিসেবে প্রথম হোস্ট ধরে রাখা
    return base_hosts[0]

def run_nlm(cmd_args, cookies, timeout=180, lang_code=None, base_url="https://notebook.google.com"):
    nlm_bin = find_nlm_binary()
    env = os.environ.copy()
    env["NOTEBOOKLM_COOKIES"] = cookies
    env["NOTEBOOKLM_BASE_URL"] = base_url
    if lang_code:
        env["NOTEBOOKLM_HL"] = lang_code
        
    full_cmd = [nlm_bin] + cmd_args
    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "কমান্ডের সময়সীমা অতিক্রম করেছে।"
    except Exception as e:
        return -1, "", str(e)

def parse_cookies_pool(raw_json_str):
    if not raw_json_str:
        return []
    try:
        data = json.loads(raw_json_str.strip())
    except Exception as e:
        print(f"[!] Error parsing COOKIES_POOL_JSON: {e}")
        return []

    accounts = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                c_str = item.strip().replace("\n", " ")
                if c_str:
                    accounts.append(c_str)
            elif isinstance(item, dict):
                if "cookies" in item and isinstance(item["cookies"], str):
                    accounts.append(item["cookies"].strip().replace("\n", " "))
                elif "cookie" in item and isinstance(item["cookie"], str):
                    accounts.append(item["cookie"].strip().replace("\n", " "))
                else:
                    c_str = "; ".join([f"{k}={v}" for k, v in item.items() if isinstance(v, str)])
                    if c_str:
                        accounts.append(c_str)
            elif isinstance(item, list):
                pairs = []
                for c in item:
                    if isinstance(c, dict) and "name" in c and "value" in c:
                        pairs.append(f"{c['name']}={c['value']}")
                if pairs:
                    accounts.append("; ".join(pairs))
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, str):
                accounts.append(v.strip().replace("\n", " "))
            elif isinstance(v, dict) and "cookies" in v:
                accounts.append(v["cookies"].strip().replace("\n", " "))
    return accounts

def extract_notebook_id(output):
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            for k in ("id", "notebook_id", "notebookId"):
                if k in data:
                    return data[k]
    except Exception:
        pass
    m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", output)
    if m:
        return m.group(1)
    m = re.search(r"(?:Created notebook|notebook[:\s]+)\s*([a-zA-Z0-9_-]{10,})", output, re.IGNORECASE)
    if m:
        return m.group(1)
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
            elif "in_progress" in lower_line or "pending" in lower_line or "creating" in lower_line:
                return "in_progress", art_id
            elif "failed" in lower_line or "error" in lower_line or "✗" in line:
                return "failed", art_id
    return "unknown", None

def folder_has_audio(folder_path):
    if not os.path.exists(folder_path):
        return False
    for f in os.listdir(folder_path):
        if f.lower().endswith(AUDIO_EXTENSIONS):
            return True
    return False

def detect_sources(workspace_dir):
    link_candidates = ["Link.txt", "link.txt", "LINK.TXT"]
    book_candidates = ["Book.txt", "book.txt", "BOOK.TXT"]
    
    for c in link_candidates:
        p = os.path.join(workspace_dir, c)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
            if urls:
                print(f"[+] সোর্স পাওয়া গেছে: {c} ফাইলে {len(urls)} টি লিঙ্ক রয়েছে।")
                return "links", urls

    for c in book_candidates:
        p = os.path.join(workspace_dir, c)
        if os.path.exists(p):
            print(f"[+] সোর্স পাওয়া গেছে: {c} ফাইলটি সোর্স হিসেবে ব্যবহার হবে।")
            return "book", p

    return None, None

def generate_podcast_for_language(lang, cookie, source_type, source_data, output_folder, base_url):
    os.makedirs(output_folder, exist_ok=True)
    # শুধুমাত্র ইংরেজি অক্ষর দিয়ে নোটবুকের নাম (যাতে ইউনিকোড এরর না হয়)
    nb_title = f"Pod_{int(time.time())}"
    print(f"[*] নোটবুক তৈরি করা হচ্ছে: '{nb_title}' ({lang['name']})...")
    
    code, out, err = run_nlm(["notebook", "create", nb_title, "--json"], cookie, lang_code=lang['code'], base_url=base_url)
    nb_id = extract_notebook_id(out)
    if not nb_id:
        code, out, err = run_nlm(["notebook", "create", nb_title], cookie, lang_code=lang['code'], base_url=base_url)
        nb_id = extract_notebook_id(out)
        
    if not nb_id:
        print(f"[-] নোটবুক তৈরিতে ব্যর্থ। এরর: {err or out}")
        return False

    print(f"[+] নোটবুক তৈরি সফল (ID: {nb_id})")
    
    try:
        print(f"[*] নোটবুকে সোর্স যুক্ত করা হচ্ছে...")
        if source_type == "links":
            for url in source_data:
                print(f"    -> লিঙ্ক যুক্ত হচ্ছে: {url}")
                s_code, s_out, s_err = run_nlm(["source", "add", nb_id, "--url", url, "--wait"], cookie, timeout=120, lang_code=lang['code'], base_url=base_url)
                if s_code != 0:
                    print(f"    [!] সতর্কতা: লিঙ্কটি যুক্ত হয়নি: {s_err or s_out}")
        elif source_type == "book":
            print(f"    -> বই ফাইলটি যুক্ত হচ্ছে: {source_data}")
            s_code, s_out, s_err = run_nlm(["source", "add", nb_id, "--file", source_data, "--wait"], cookie, timeout=180, lang_code=lang['code'], base_url=base_url)
            if s_code != 0:
                print(f"[-] বই সোর্স যুক্ত করতে ব্যর্থ: {s_err or s_out}")
                return False

        custom_prompt = f"Generate the podcast entirely in {lang['prompt_lang']}."
        print(f"[*] অডিও জেনারেশন রিকোয়েস্ট পাঠানো হচ্ছে: {lang['name']} (কোড: {lang['code']})...")
        
        a_code, a_out, a_err = run_nlm([
            "audio", "create", nb_id,
            "--language", lang['code'],
            "--focus", custom_prompt,
            "--confirm"
        ], cookie, timeout=120, lang_code=lang['code'], base_url=base_url)
        
        if a_code != 0:
            print(f"[-] অডিও জেনারেশন শুরু করতে ব্যর্থ: {a_err or a_out}")
            return False

        print(f"[+] অডিও জেনারেশন শুরু হয়েছে ({lang['name']})।")

        max_wait_seconds = 1800
        poll_interval = 300
        elapsed_seconds = 0
        audio_completed = False
        target_art_id = None

        print(f"[*] স্ট্যাটাস পর্যবেক্ষণ চলছে (প্রতি ৫ মিনিট পর পর চেক, সর্বোচ্চ ৩০ মিনিট)...")
        while elapsed_seconds < max_wait_seconds:
            print(f"    ৫ মিনিট অপেক্ষা করা হচ্ছে... (অতিবাহিত সময়: {elapsed_seconds // 60} মিনিট)")
            time.sleep(poll_interval)
            elapsed_seconds += poll_interval

            st_code, st_out, st_err = run_nlm(["studio", "status", nb_id, "--json"], cookie, timeout=60, lang_code=lang['code'], base_url=base_url)
            status, art_id = check_audio_status(st_out)
            if status == "unknown":
                st_code, st_out, st_err = run_nlm(["studio", "status", nb_id], cookie, timeout=60, lang_code=lang['code'], base_url=base_url)
                status, art_id = check_audio_status(st_out)

            print(f"    [{elapsed_seconds // 60} মিনিটে স্ট্যাটাস]: {status.upper()} (Artifact ID: {art_id})")

            if status == "completed":
                audio_completed = True
                target_art_id = art_id
                break
            elif status == "failed":
                print(f"[-] NotebookLM জানিয়েছে অডিও তৈরিতে সমস্যা হয়েছে।")
                return False

        if not audio_completed:
            print(f"[-] ৩০ মিনিটের মধ্যে অডিও তৈরি সম্পন্ন হয়নি (টাইমআউট)।")
            return False

        temp_audio_file = f"/tmp/nlm_audio_{lang['folder']}_{int(time.time())}.m4a"
        print(f"[*] অডিও ডাউনলোড করা হচ্ছে...")
        
        dl_cmd = ["download", "audio", nb_id, "--output", temp_audio_file]
        if target_art_id:
            dl_cmd = ["download", "audio", nb_id, "--id", target_art_id, "--output", temp_audio_file]
            
        d_code, d_out, d_err = run_nlm(dl_cmd, cookie, timeout=180, lang_code=lang['code'], base_url=base_url)
        if d_code != 0 or not os.path.exists(temp_audio_file):
            dl_cmd = ["download", "audio", nb_id, "--output", temp_audio_file]
            d_code, d_out, d_err = run_nlm(dl_cmd, cookie, timeout=180, lang_code=lang['code'], base_url=base_url)

        if not os.path.exists(temp_audio_file) or os.path.getsize(temp_audio_file) == 0:
            print(f"[-] অডিও ফাইল ডাউনলোড করা যায়নি: {d_err or d_out}")
            return False

        target_mp3 = os.path.join(output_folder, "podcast_audio.mp3")
        print(f"[*] অডিও ফাইল সেভ করা হচ্ছে: {target_mp3}...")
        conv_res = subprocess.run([
            "ffmpeg", "-y", "-i", temp_audio_file,
            "-c:a", "libmp3lame", "-q:a", "2",
            target_mp3
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if conv_res.returncode != 0 or not os.path.exists(target_mp3):
            target_m4a = os.path.join(output_folder, "podcast_audio.m4a")
            shutil.copyfile(temp_audio_file, target_m4a)
            print(f"[!] M4A ফরম্যাটে সেভ হয়েছে: {target_m4a}")
        else:
            print(f"[+] সফলভাবে MP3 অডিও সেভ হয়েছে: {target_mp3}")

        if os.path.exists(temp_audio_file):
            try:
                os.remove(temp_audio_file)
            except Exception:
                pass

        return True

    finally:
        print(f"[*] রিমোট নোটবুক মুছে ফেলা হচ্ছে...")
        run_nlm(["notebook", "delete", nb_id, "--confirm"], cookie, timeout=60, lang_code=lang['code'], base_url=base_url)

def main():
    parser = argparse.ArgumentParser(description="NotebookLM Multi-Account Audio Generator")
    parser.add_argument("--workspace", default="./Workspace", help="Path to Workspace directory")
    parser.add_argument("--channels_config", default="channels_config.json", help="Path to channels_config.json")
    args = parser.parse_args()

    workspace_dir = os.path.abspath(args.workspace)
    if not os.path.exists(workspace_dir):
        print(f"Error: Workspace ফোল্ডার পাওয়া যায়নি: '{workspace_dir}'")
        sys.exit(1)

    channels_cfg = load_channels_config(args.channels_config)

    raw_cookies_json = os.environ.get("COOKIES_POOL_JSON")
    if not raw_cookies_json:
        print("Error: GitHub Secrets-এ 'COOKIES_POOL_JSON' সেট করা নেই।")
        sys.exit(1)

    accounts = parse_cookies_pool(raw_cookies_json)
    if not accounts:
        print("Error: COOKIES_POOL_JSON থেকে কোনো অ্যাকাউন্ট পাওয়া যায়নি।")
        sys.exit(1)

    print(f"[+] মোট {len(accounts)} টি গুগল অ্যাকাউন্ট লোড হয়েছে।")

    source_type, source_data = detect_sources(workspace_dir)
    if not source_type:
        print(f"Error: {workspace_dir} ফোল্ডারে Link.txt বা Book.txt পাওয়া যায়নি।")
        sys.exit(1)

    current_account_index = 0
    audios_on_current_account = 0

    print("\n=======================================================")
    print("    NOTEBOOKLM MULTI-LANGUAGE AUDIO PIPELINE STARTED   ")
    print("=======================================================\n")

    # বর্তমান অ্যাকাউন্টের সেশন প্রস্তুত করা
    current_cookie = accounts[current_account_index]
    active_base_url = setup_account_session(current_cookie)

    for idx, lang in enumerate(LANGUAGE_CONFIG, 1):
        lang_folder = os.path.join(workspace_dir, lang["folder"])
        
        if not is_channel_enabled(lang, channels_cfg):
            print(f"[{idx}/{len(LANGUAGE_CONFIG)}] [বন্ধ রাখা হয়েছে] '{lang['channel']}' channels_config.json-এ বন্ধ (False)। স্কিপ করা হলো।")
            continue

        if folder_has_audio(lang_folder):
            print(f"[{idx}/{len(LANGUAGE_CONFIG)}] [SKIP] '{lang['folder']}' এ অডিও আগে থেকেই আছে। স্কিপ করা হচ্ছে।")
            continue

        if audios_on_current_account >= 3:
            print(f"\n[🔄 রোটেশন] অ্যাকাউন্ট #{current_account_index + 1}-এ ৩টি অডিও তৈরি শেষ। পরবর্তী অ্যাকাউন্টে সুইচ করা হচ্ছে...")
            current_account_index = (current_account_index + 1) % len(accounts)
            audios_on_current_account = 0
            current_cookie = accounts[current_account_index]
            active_base_url = setup_account_session(current_cookie)
            switch_delay = random.randint(120, 300)
            print(f"[⏳ অ্যান্টি-ব্যান] বিরতি: {switch_delay} সেকেন্ড স্লিপ হচ্ছে...\n")
            time.sleep(switch_delay)

        lang_success = False
        attempt = 0
        max_attempts = len(accounts)

        while not lang_success and attempt < max_attempts:
            current_cookie = accounts[current_account_index]
            print(f"\n>>> [{idx}/{len(LANGUAGE_CONFIG)}] {lang['name']} ({lang['folder']}) অডিও তৈরি শুরু <<<")
            print(f"    ব্যবহার করা হচ্ছে অ্যাকাউন্ট #{current_account_index + 1} (হোস্ট: {active_base_url})")

            success = generate_podcast_for_language(lang, current_cookie, source_type, source_data, lang_folder, active_base_url)

            if success:
                lang_success = True
                audios_on_current_account += 1
                print(f"[✓ সফল] {lang['name']} অডিও তৈরি হয়েছে ({audios_on_current_account}/3)")
                post_gen_delay = random.randint(120, 300)
                print(f"[⏳ অ্যান্টি-ব্যান] স্লিপ: {post_gen_delay} সেকেন্ড...\n")
                time.sleep(post_gen_delay)
            else:
                print(f"[✗ ব্যর্থ] অ্যাকাউন্ট #{current_account_index + 1} ফেইল হয়েছে। পরবর্তী অ্যাকাউন্টে যাচ্ছি...")
                current_account_index = (current_account_index + 1) % len(accounts)
                audios_on_current_account = 0
                current_cookie = accounts[current_account_index]
                active_base_url = setup_account_session(current_cookie)
                attempt += 1
                fail_delay = random.randint(120, 300)
                print(f"[⏳ অ্যান্টি-ব্যান] স্লিপ: {fail_delay} সেকেন্ড...\n")
                time.sleep(fail_delay)

        if not lang_success:
            print(f"[!] সতর্কতা: {lang['name']} এর অডিও তৈরি সম্ভব হয়নি।")

    print("\n=======================================================")
    print("      NOTEBOOKLM অডিও পাইপলাইন সম্পন্ন হয়েছে!          ")
    print("=======================================================\n")

if __name__ == "__main__":
    main()
