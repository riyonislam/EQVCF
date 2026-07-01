import os
import argparse
import subprocess
import concurrent.futures
from PIL import Image, ImageStat

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

def process_videos(base_folder_path, max_workers, viz_white, viz_black):
    print(f"Scanning base folder: {base_folder_path}")
    subfolders = sorted([f for f in os.listdir(base_folder_path) if os.path.isdir(os.path.join(base_folder_path, f)) and f.lower() != "summary"])
    folders_to_process = [os.path.join(base_folder_path, f) for f in subfolders]

    if not folders_to_process:
        print("No language folders found.")
        return

    print(f"Total folders found: {len(folders_to_process)}. Starting execution...")

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
    
    args = parser.parse_args()
    process_videos(args.input, args.workers, args.viz_white, args.viz_black)