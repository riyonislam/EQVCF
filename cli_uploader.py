import os
import re
import glob
import argparse
from datetime import datetime, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
API_SERVICE_NAME, API_VERSION = 'youtube', 'v3'

SECRETS_DIR = 'Client_Secrets'
CREDENTIALS_DIR = 'Credentials_Storage'

LANGUAGE_TO_CHANNEL_MAP = {'English':'NextRead English','Summary':'NextRead Summary','Deutsch':'NextRead Deutsch','Nederlands':'NextRead Nederlands','বাংলা':'NextRead বাংলা','हिन्दी':'NextRead हिन्दी','العربية':'NextRead العربية','中文':'NextRead 中文 (繁體)','日本語':'NextRead 日本語','Русский':'NextRead Русский','Türkçe':'NextRead Türkçe','Polski':'NextRead Polski','Português':'NextRead Português','Indonesia':'NextRead Indonesia','한국어':'NextRead 한국어','Italiano':'NextRead Italiano','ελληνικά':'NextRead ελληνικά','Tiếng Việt':'NextRead Tiếng Việt','Français':'NextRead Français','Español':'NextRead Español','Norsk':'NextRead Norsk'}
LANGUAGE_TO_FOLDER_MAP = {'English':'English','Summary':'Summary','Deutsch':'Deutsch','Nederlands':'Nederlands','বাংলা':'বাংলা','हिन्दी':'हिन्दी','العربية':'العربية','中文':'中文','日本語':'日本語','Русский':'Русский','Türkçe':'Türkçe','Polski':'Polski','Português':'Português','Indonesia':'Indonesia','한국어':'한국어','Italiano':'Italiano','ελληνικά':'ελληνικά','Tiếng Việt':'Tiếng Việt','Français':'Français','Español':'Español','Norsk':'Norsk'}
CHANNEL_TO_ACCOUNT_MAP = {'NextRead English':'main_en','NextRead Summary':'main_sum','NextRead Deutsch':'main_de','NextRead Nederlands':'main_nl','NextRead বাংলা':'main_bn','NextRead हिन्दी':'main_hi','NextRead العربية':'main_ar','NextRead 中文 (繁體)':'main_zh','NextRead 日本語':'main_ja','NextRead Русский':'main_ru','NextRead Türkçe':'main_tr','NextRead Polski':'main_pl','NextRead Português':'main_pt','NextRead Indonesia':'main_id','NextRead 한국어':'main_ko','NextRead Italiano':'main_it','NextRead ελληνικά':'main_el','NextRead Tiếng Việt':'main_vi','NextRead Français':'france_spain_fr','NextRead Español':'france_spain_es','NextRead Norsk':'norway_no'}

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

def get_authenticated_service(account_key, client_secret_file):
    credentials_path = os.path.join(CREDENTIALS_DIR, f'credentials_{account_key}.json')
    if os.path.exists(credentials_path):
        credentials = Credentials.from_authorized_user_file(credentials_path, SCOPES)
    else:
        raise FileNotFoundError(f"Credentials not found for {account_key}")
        
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            print(f"Refreshing credentials for '{account_key}'...")
            credentials.refresh(Request())
            with open(credentials_path, 'w') as f:
                f.write(credentials.to_json())
        else:
            raise Exception(f"OAuth credentials for {account_key} expired/invalid.")
            
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

    with open(ai_text_path, 'r', encoding='utf-8') as f:
        ai_content = f.read()

    parsed_metadata = parse_ai_output(ai_content)
    json_files = glob.glob(os.path.join(SECRETS_DIR, '*.json'))
    if not json_files:
        print("Fatal Error: No client secrets JSON found.")
        return
    client_secret_file = json_files[0]

    # গিটহাব রান করার সময় কোন কোন ফোল্ডারে নতুন ভিডিও তৈরি হয়েছে তা অটোমেটিক ডিটেক্ট করবে
    for folder_name in os.listdir(base_folder):
        media_folder_path = os.path.join(base_folder, folder_name)
        if not os.path.isdir(media_folder_path) or folder_name.lower() == "summary":
            continue

        video_file, thumbnail_file = find_media_files(media_folder_path)
        if not video_file:
            continue # এই ফোল্ডারে নতুন কোনো ভিডিও তৈরি হয়নি

        # ভাষা শনাক্তকরণ
        lang = next((l for l, f in LANGUAGE_TO_FOLDER_MAP.items() if f == folder_name), None)
        if not lang or lang not in parsed_metadata:
            print(f"Skipping {folder_name}: No metadata found in AI text.")
            continue

        metadata = parsed_metadata[lang]
        channel_name = LANGUAGE_TO_CHANNEL_MAP.get(lang)
        account_key = CHANNEL_TO_ACCOUNT_MAP.get(channel_name)

        print(f"\n>>> Uploading to Channel: {channel_name} (Lang: {lang}) <<<")
        try:
            youtube_service = get_authenticated_service(account_key, client_secret_file)
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
                print(f"Scheduling video for: {schedule_time_str} UTC")

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
    parser.add_argument('--mode', choices=['now', 'schedule'], default='now')
    parser.add_argument('--schedule_time', default=None)
    args = parser.parse_args()

    run_uploader(args.input, args.ai_text, args.mode, args.schedule_time)