import os
import json
import argparse
import subprocess
import concurrent.futures
from PIL import Image, ImageStat

EXCLUDED_FOLDERS = {"summary", "thumbnail fonts", "fonts"}

FOLDER_TO_CHANNEL = {
    'English': 'NextRead English',
    'Summary': 'NextRead Summary',
    'Deutsch': 'NextRead Deutsch',
    'Nederlands': 'NextRead Nederlands',
    'বাংলা': 'NextRead বাংলা',
    'हिन्दी': 'NextRead हिन्दी',
    'العربية': 'NextRead العربية',
    '中文': 'NextRead 中文 (繁體)',
    '日本語': 'NextRead 日本語',
    'Русский': 'NextRead Русский',
    'Türkçe': 'NextRead Türkçe',
    'Polski': 'NextRead Polski',
    'Português': 'NextRead Português',
    'Indonesia': 'NextRead Indonesia',
    '한국어': 'NextRead 한국어',
    'Italiano': 'NextRead Italiano',
    'ελληνικά': 'NextRead ελληνικά',
    'Tiếng Việt': 'NextRead Tiếng Việt',
    'Français': 'NextRead Français',
    'Español': 'NextRead Español',
    'Norsk': 'NextRead Norsk'
}

def load_channels_config(config_path="channels_config.json"):
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not read {config_path}: {e}")
    return {}

def is_channel_enabled(folder_name, channels_cfg):
    if not channels_cfg:
        return True
    channel_name = FOLDER_TO_CHANNEL.get(folder_name, folder_name)
    if channel_name in channels_cfg:
        return bool(channels_cfg[channel_name])
    if folder_name in channels_cfg:
        return bool(channels_cfg[folder_name])
    return True

def is_background_dark(image_path, threshold=128):
    try:
        with Image.open(image_path) as img:
            grayscale_img = img.convert('L')
            stat = ImageStat.Stat(grayscale_img)
            avg_brightness = stat.mean[0]
            return avg_brightness < threshold
    except Exception as e:
        print(f"Warning: Could not analyze image brightness for {os.path.basename(image_path)}: {e}")
        return True

def create_video_with_ffmpeg(folder_path, viz_white, viz_black):
    image_path = None
    audio_source_path = None 
    video_for_audio_path = None 
    
    output_filename = os.path.join(folder_path, "output_video.mp4")

    image_extensions = ('.png', '.jpg', '.jpeg', '.bmp')
    audio_extensions = ('.mp3', '.wav', '.m4a', '.ogg', '.flac')
    video_extensions_for_audio = ('.mp4',)

    for file in os.listdir(folder_path):
        lower_file = file.lower()
        full_path = os.path.join(folder_path, file)
        
        if not image_path and lower_file.endswith(image_extensions):
            image_path = full_path
        if not audio_source_path and lower_file.endswith(audio_extensions):
            audio_source_path = full_path
        if not video_for_audio_path and lower_file.endswith(video_extensions_for_audio):
            video_for_audio_path = full_path

    if not audio_source_path and video_for_audio_path:
        print(f"Info in '{os.path.basename(folder_path)}': Using audio from video '{os.path.basename(video_for_audio_path)}'.")
        audio_source_path = video_for_audio_path
            
    if not image_path: return f"Skipped: No image file in '{os.path.basename(folder_path)}'"
    if not audio_source_path: return f"Skipped: No audio or MP4 file in '{os.path.basename(folder_path)}'"

    if is_background_dark(image_path):
        visualizer_path = viz_white
    else:
        visualizer_path = viz_black

    if not os.path.exists(visualizer_path):
        return f"Fatal Error: visualizer GIF not found at '{visualizer_path}'"

    try:
        filter_complex_string = '[1:v][0:v]scale2ref=w=iw*0.46:h=-1[viz][bg];[bg][viz]overlay=x=main_w*0.50:y=main_h*0.59[outv]'
        command = [
            'ffmpeg', '-y', '-nostdin', '-hide_banner', '-stats',
            '-loop', '1', '-i', image_path,            
            '-ignore_loop', '0', '-i', visualizer_path,
            '-i', audio_source_path,                   
            '-filter_complex', filter_complex_string,
            '-map', '[outv]', '-map', '2:a',        
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', output_filename
        ]
        
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Success: Video created for '{os.path.basename(folder_path)}'"

    except subprocess.CalledProcessError:
        return f"FFMPEG Error in '{os.path.basename(folder_path)}'."
    except Exception as e:
        return f"Python Error in '{os.path.basename(folder_path)}': {e}"

def process_videos(base_folder_path, max_workers, viz_white, viz_black, channels_config_path="channels_config.json"):
    print(f"Scanning base folder: {base_folder_path}")
    channels_cfg = load_channels_config(channels_config_path)

    subfolders = sorted([
        f for f in os.listdir(base_folder_path) 
        if os.path.isdir(os.path.join(base_folder_path, f)) and f.lower() not in EXCLUDED_FOLDERS
    ])
    
    folders_to_process = []
    for f in subfolders:
        ch_name = FOLDER_TO_CHANNEL.get(f, f)
        if not is_channel_enabled(f, channels_cfg):
            print(f"[বন্ধ রাখা হয়েছে] '{ch_name}' ({f}) channels_config.json-এ বন্ধ (False) আছে। ভিডিও তৈরি স্কিপ করা হলো।")
            continue
        folders_to_process.append(os.path.join(base_folder_path, f))

    if not folders_to_process:
        print("No active language folders found for video generation.")
        return

    print(f"\nTotal active folders to process: {len(folders_to_process)}. Starting video generation...")

    success_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_folder = {executor.submit(create_video_with_ffmpeg, path, viz_white, viz_black): path for path in folders_to_process}
        
        for future in concurrent.futures.as_completed(future_to_folder):
            result = future.result()
            print(result)
            if "Success" in result:
                success_count += 1
                
    print(f"\nProcessing Complete! {success_count} of {len(folders_to_process)} videos created successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto Video Creator - CLI")
    parser.add_argument('--input', type=str, required=True, help="Base folder containing all subfolders")
    parser.add_argument('--viz_white', type=str, required=True, help="Path to white GIF")
    parser.add_argument('--viz_black', type=str, required=True, help="Path to black GIF")
    parser.add_argument('--workers', type=int, default=4, help="Number of concurrent exports")
    parser.add_argument('--channels_config', type=str, default='channels_config.json', help="Path to channels_config.json")
    
    args = parser.parse_args()
    process_videos(args.input, args.workers, args.viz_white, args.viz_black, args.channels_config)
