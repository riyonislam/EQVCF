import os
import re
import glob
import argparse
from datetime import datetime, timezone, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
API_SERVICE_NAME, API_VERSION = 'youtube', 'v3'

LANGUAGE_TO_CHANNEL_MAP = {'English':'NextRead English','Summary':'NextRead Summary','Deutsch':'NextRead Deutsch','Nederlands':'NextRead Nederlands','বাংলা':'NextRead বাংলা','हिन्दी':'NextRead हिन्दी','العربية':'NextRead العربية','中文':'NextRead 中文 (繁體)','日本語':'NextRead 日本語','Русский':'NextRead Русский','Türkçe':'NextRead Türkçe','Polski':'NextRead Polski','Português':'NextRead Português','Indonesia':'NextRead Indonesia','한국어':'NextRead 한국어','Italiano':'NextRead Italiano','ελληνικά':'NextRead ελληνικά','Tiếng Việt':'NextRead Tiếng Việt','Français':'NextRead Français','Español':'NextRead Español','Norsk':'NextRead Norsk'}
LANGUAGE_TO_FOLDER_MAP = {'English':'English','Summary':'Summary','Deutsch':'Deutsch','Nederlands':'Nederlands','বাংলা':'বাংলা','हिन्दी':'हिन्दी','العربية':'العربية','中文':'中文','日本語':'日本語','Русский':'Русский','Türkçe':'Türkçe','Polski':'Polski','Português':'Português','Indonesia':'Indonesia','한국어':'한국어','Italiano':'Italiano','ελληνικά':'ελληνικά','Tiếng Việt':'Tiếng Việt','Français':'Français','Español':'Español','Norsk':'Norsk'}
CHANNEL_TO_ACCOUNT_MAP = {'NextRead English':'main_en','NextRead Summary':'main_sum','NextRead Deutsch':'main_de','NextRead Nederlands':'main_nl','NextRead বাংলা':'main_bn','NextRead हिन्दी':'main_hi','NextRead العربية':'main_ar','NextRead 中文 (繁體)':'main_zh','NextRead 日本語':'main_ja','NextRead Русский':'main_ru','NextRead Türkçe':'main_tr','NextRead Polski':'main_pl','NextRead Português':'main_pt','NextRead Indonesia':'main_id','NextRead 한국어':'main_ko','NextRead Italiano':'main_it','NextRead ελληνικά':'main_el','NextRead Tiếng Việt':'main_vi','NextRead Français':'france_spain_fr','NextRead Español':'france_spain_es','NextRead Norsk':'norway_no'}

# অ্যাকাউন্ট কি থেকে গিটহাব এনভায়রনমেন্ট ভ্যারিয়েবলের নামের ম্যাপিং
ACCOUNT_TO_ENV_MAP = {
    'main_en': 'REFRESH_TOKEN_EN',
    'main_sum': 'REFRESH_TOKEN_SUM',
    'main_de': 'REFRESH_TOKEN_DE',
    'main_nl': 'REFRESH_TOKEN_NL',
    'main_bn': 'REFRESH_TOKEN_BN',
    'main_hi': 'REFRESH_TOKEN_HI',
    'main_ar': 'REFRESH_TOKEN_AR',
    'main_zh': 'REFRESH_TOKEN_ZH',
    'main_ja': 'REFRESH_TOKEN_JA',
    'main_ru': 'REFRESH_TOKEN_RU',
    'main_tr': 'REFRESH_TOKEN_TR',
    'main_pl': 'REFRESH_TOKEN_PL',
    'main_pt': 'REFRESH_TOKEN_PT',
    'main_id': 'REFRESH_TOKEN_ID',
    'main_ko': 'REFRESH_TOKEN_KO',
    'main_it': 'REFRESH_TOKEN_IT',
    'main_el': 'REFRESH_TOKEN_EL',
    'main_vi': 'REFRESH_TOKEN_VI',
    'france_spain_fr': 'REFRESH_TOKEN_FR',
    'france_spain_es': 'REFRESH_TOKEN_ES',
    'norway_no': 'REFRESH_TOKEN_NO'
}

def calculate_upload_schedule():
    now_utc = datetime.now(timezone.utc)
    bd_tz = timezone(timedelta(hours=6))
    now_bd = now_utc.astimezone(bd_tz)
    current_bd_hour = now_bd.hour

    if current_bd_hour == 23:
        print("INFO [Auto-Schedule]: Current BD Time is between 11:00 PM and 12:00 AM. Mode: PUBLISH NOW.")
        return 'now', None
    else:
        schedule_date_bd = now_bd.replace(hour=23, minute=0, second=0, microsecond=0)
        schedule_utc = schedule_date_bd.astimezone(timezone.utc)
        schedule_iso = schedule_utc.isoformat().replace("+00:00", "Z")
        
        print(f"INFO [Auto-Schedule]: Current BD Time is {now_bd.strftime('%Y-%m-%d %I:%M %p')}.")
        print(f"INFO [Auto-Schedule]: Action: SCHEDULED for {schedule_date_bd.strftime('%I:%M %p')} BST (UTC ISO: {schedule_iso})")
        return 'schedule', schedule_iso

def parse_ai_output(full_text):
    metadata = {}
    pattern = re.compile(r"===START:\s*(.*?)\s*===(.*?)===END:", re.DOTALL)
    for match in pattern.finditer(full_text):
        lang_key = match.group(1).strip()
        content = match.group(2)
        if lang_key == "中文 (繁體)": lang_key = "中文"
        if lang_key == "Bahasa Indonesia": lang_key = "Indonesia"
        
        try:
            title_match = re.search(r"TITLE:\s*(.*)", content, re.IGNORECASE)
            desc_match = re.search(r"DESCRIPTION:(.*?)(?=THUMBNAIL SLOGAN:|TAGS:)", content, re.IGNORECASE | re.DOTALL)
            tags_match = re.search(r"TAGS:\s*(.*)", content, re.IGNORECASE)
            
            if title_match and desc_match and tags_match:
                title = title_match.group(1).strip().strip('"')
                metadata[lang_key] = {
                    "title": title[:100], 
                    "description": desc_match.group(1).strip(), 
                    "tags": tags_match.group(1).strip()
                }
        except Exception as e:
            print(f"Error parsing metadata for {lang_key}: {e}")
    return metadata

def get_authenticated_service_env(account_key):
    """
    গিটহাব সিক্রেট (Environment Variables) থেকে টোকেন পড়ে অথেনটিকেশন করার পদ্ধতি
    """
    client_id = os.environ.get('YT_CLIENT_ID')
    client_secret = os.environ.get('YT_CLIENT_SECRET')
    
    env_var_name = ACCOUNT_TO_ENV_MAP.get(account_key)
    refresh_token = os.environ.get(env_var_name)
    
    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(f"Error: Missing auth secrets for '{account_key}'. Ensure YT_CLIENT_ID, YT_CLIENT_SECRET, and {env_var_name} are configured in GitHub Secrets.")
        
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES
    )
    
    # টোকেন সচল আছে কি না তা রিফ্রেশ করে নিশ্চিত করা
    credentials.refresh(Request())
    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

def find_media_files(folder_path):
    video_file = os.path.join(folder_path, 'output_video.mp4')
    if not os.path.exists(video_file):
        video_file = None
    thumbnail_file = None
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        found = glob.glob(os.path.join(folder_path, ext))
        if found:
            thumbnail_file = sorted(found)[0]
            break
    return video_file, thumbnail_file

def run_uploader(base_folder, ai_text_path, mode, schedule_time_str=None):
    if not os.path.exists(ai_text_path):
        print(f"Error: AI Text file not found at {ai_text_path}")
        return

    if mode == 'auto':
        mode, schedule_time_str = calculate_upload_schedule()

    with open(ai_text_path, 'r', encoding='utf-8') as f:
        ai_content = f.read()

    parsed_metadata = parse_ai_output(ai_content)

    for folder_name in os.listdir(base_folder):
        media_folder_path = os.path.join(base_folder, folder_name)
        if not os.path.isdir(media_folder_path) or folder_name.lower() == "summary":
            continue

        video_file, thumbnail_file = find_media_files(media_folder_path)
        if not video_file:
            continue

        lang = next((l for l, f in LANGUAGE_TO_FOLDER_MAP.items() if f == folder_name), None)
        if not lang or lang not in parsed_metadata:
            print(f"Skipping {folder_name}: No metadata found in AI text.")
            continue

        metadata = parsed_metadata[lang]
        channel_name = LANGUAGE_TO_CHANNEL_MAP.get(lang)
        account_key = CHANNEL_TO_ACCOUNT_MAP.get(channel_name)

        print(f"\n>>> Uploading to Channel: {channel_name} (Lang: {lang}) <<<")
        try:
            # নতুন এনভায়রনমেন্ট অথেনটিকেশন ফাংশন কল করা হয়েছে
            youtube_service = get_authenticated_service_env(account_key)
            body = {
                'snippet': {
                    'title': metadata['title'],
                    'description': metadata['description'],
                    'tags': [t.strip() for t in metadata['tags'].split(',')],
                    'categoryId': '22'
                },
                'status': {'privacyStatus': 'public'}
            }

            if mode == 'schedule' and schedule_time_str:
                body['status']['privacyStatus'] = 'private'
                body['status']['publishAt'] = schedule_time_str

            media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
            request = youtube_service.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
            response = request.execute()
            print(f"SUCCESS: Video uploaded. ID: {response['id']}")

            if thumbnail_file:
                try:
                    youtube_service.thumbnails().set(videoId=response['id'], media_body=MediaFileUpload(thumbnail_file)).execute()
                    print("SUCCESS: Thumbnail set successfully.")
                except Exception as thumb_err:
                    print(f"Warning: Thumbnail upload failed: {thumb_err}")

        except Exception as err:
            print(f"Failed to upload for {lang}: {err}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--ai_text', required=True)
    parser.add_argument('--mode', choices=['now', 'schedule', 'auto'], default='auto')
    parser.add_argument('--schedule_time', default=None)
    args = parser.parse_args()

    run_uploader(args.input, args.ai_text, args.mode, args.schedule_time)