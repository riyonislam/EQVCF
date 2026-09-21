import os
import re
import io
import time
import json
import random
import urllib.parse
import argparse
import requests
from PIL import Image, ImageDraw, ImageFont, features

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_ARABIC_RESHAPER = True
except ImportError:
    HAS_ARABIC_RESHAPER = False

try:
    from langdetect import detect, LangDetectException
    HAS_LANGDETECT = True
except ImportError:
    HAS_LANGDETECT = False

try:
    HAS_RAQM = features.check_module('raqm')
except Exception:
    HAS_RAQM = False

TEXT_PANEL_START_X_RATIO = 0.46
TARGET_MAX_SIZE_MB = 1.5
TARGET_MAX_BYTES = int(TARGET_MAX_SIZE_MB * 1024 * 1024)

LANGUAGE_FOLDERS = [
    'Deutsch', 'English', 'Español', 'Français', 'Indonesia',
    'Italiano', 'Nederlands', 'Norsk', 'Polski', 'Português',
    'Tiếng Việt', 'Türkçe', 'ελληνικά', 'Русский', 'العربية',
    'हिन्दी', 'বাংলা', '한국어', '中文', '日本語'
]

def fix_complex_scripts(text, lang_mode):
    if not HAS_RAQM:
        if lang_mode == "বাংলা":
            text = re.sub(r'([\u0995-\u09B9\u09CE](?:\u09CD[\u0995-\u09B9\u09CE])*)([\u09BF\u09C7\u09C8])', r'\2\1', text)
        elif lang_mode == "हिन्दी":
            text = re.sub(r'([\u0915-\u0939](?:\u094D[\u0915-\u0939])*)([\u093F])', r'\2\1', text)

    if HAS_ARABIC_RESHAPER and lang_mode == "العربية":
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text
    
    return text

class FontManager:
    def __init__(self, log_callback=print): 
        self.fonts_map = {}
        self.log_callback = log_callback

    def scan_font_folder(self, base_folder_path):
        if not base_folder_path or not os.path.isdir(base_folder_path): 
            return False
            
        for lang_folder in os.listdir(base_folder_path):
            folder_path = os.path.join(base_folder_path, lang_folder)
            if os.path.isdir(folder_path):
                for file_name in os.listdir(folder_path):
                    if file_name.lower().endswith(('.ttf', '.otf', '.ttc')):
                        self.fonts_map[lang_folder] = os.path.join(folder_path, file_name)
                        break
                        
        if self.fonts_map:
            self.log_callback(f"[+] ফন্ট লোড সফল: '{base_folder_path}' ফোল্ডার থেকে {len(self.fonts_map)} টি ভাষার ফন্ট পাওয়া গেছে।")
            return True
        return False

    def get_font_file_path(self, target_folder_name):
        font_path = self.fonts_map.get(target_folder_name)
        if font_path: return target_folder_name, font_path
        
        eng_fallback = self.fonts_map.get("English")
        if eng_fallback: return "English (Fallback)", eng_fallback
        
        if self.fonts_map: 
            return "Fallback", list(self.fonts_map.values())[0]
            
        return target_folder_name, None

def get_ot_lang_tag(folder_name):
    tags = {
        'বাংলা': 'bn', 'हिन्दी': 'hi', 'العربية': 'ar', 'ελληνικά': 'el', 
        'Tiếng Việt': 'vi', 'Русский': 'ru', '한국어': 'ko', 
        '日本語': 'ja', '中文': 'zh', 'English': 'en', 'Español': 'es', 'Français': 'fr'
    }
    return tags.get(folder_name, 'en')

def robust_bbox_and_draw(mode, draw_obj, text, font, xy, kwargs, is_drawing=False):
    if 'language' in kwargs and not HAS_RAQM:
        del kwargs['language']
    
    if is_drawing:
        try:
            draw_obj.text(xy, text, font=font, **kwargs)
        except Exception: 
            kwargs.pop('language', None)
            draw_obj.text(xy, text, font=font, **kwargs)
        return None
    else:
        try:
            return draw_obj.textbbox((0,0), text, font=font, **kwargs)
        except Exception:
            kwargs.pop('language', None)
            return draw_obj.textbbox((0,0), text, font=font, **kwargs)

def get_optimal_font(draw, text, font_path, max_width, max_size, engine_lang):
    for size in range(max_size, 10, -5):
        try:
            font = ImageFont.truetype(font_path, size)
        except Exception:
            font = ImageFont.load_default()
            return font
            
        kwargs = {} if not engine_lang else {'language': engine_lang}
        bbox = robust_bbox_and_draw('bbox', draw, text, font, (0,0), kwargs, False)
        length = bbox[2] - bbox[0]
        if length <= max_width:
            return font
            
    try:
        return ImageFont.truetype(font_path, 10)
    except Exception:
        return ImageFont.load_default()

def split_text_compactly(text):
    words = text.split(); n = len(words)
    if n == 0: return []
    if n <= 3: return [" ".join(words)]
    else: mid = (n + 1) // 2; return [" ".join(words[:mid]), " ".join(words[mid:])]

def split_text_smartly(text):
    words = text.split(); n = len(words)
    if n == 0: return []
    if n <= 4: mid = (n + 1) // 2; return [" ".join(words[:mid]), " ".join(words[mid:])]
    else:
        part_len, remainder = divmod(n, 3); breaks = [0]
        for i in range(3): breaks.append(breaks[-1] + part_len + (1 if i < remainder else 0))
        return [" ".join(words[breaks[i]:breaks[i+1]]) for i in range(3)]

def draw_text_with_optional_bg(draw, text, font, settings_key, x_pos, y_pos, appearance_settings, engine_lang, apply_stroke=True):
    kwargs = {} if not engine_lang else {'language': engine_lang}
    bbox = robust_bbox_and_draw('bbox', draw, text, font, (0,0), kwargs, False)
    
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    if appearance_settings.get(f'use_{settings_key}_bg', False):
        bg_color = appearance_settings.get(f'{settings_key}_bg_color', '#000000')
        pad_x, pad_y = (25, 15) if settings_key == 'audiobook' else (60, 30)
        box_w, box_h = w + 2 * pad_x, h + 2 * pad_y
        box_x, box_y = x_pos - pad_x, y_pos - pad_y + bbox[1]
        draw.rounded_rectangle([box_x, box_y, box_x + box_w, box_y + box_h], radius=15, fill=bg_color)

    fill_color = appearance_settings.get(f'{settings_key}_color', '#FFFFFF')
    final_x = x_pos - bbox[0]
    
    draw_kwargs = {'fill': fill_color}
    if engine_lang: draw_kwargs['language'] = engine_lang

    if apply_stroke and appearance_settings.get(f'apply_stroke_for_{settings_key}', True):
        font_sz = getattr(font, 'size', 40)
        draw_kwargs['stroke_width'] = max(1, int(font_sz / 40))
        draw_kwargs['stroke_fill'] = fill_color

    robust_bbox_and_draw('draw', draw, text, font, (final_x, y_pos), draw_kwargs, True)

def extract_slogans_from_ai_text(text):
    slogans = {}
    pattern = re.compile(r"===START:\s*(.*?)\s*===(.*?)===END:", re.DOTALL)
    for match in pattern.finditer(text):
        lang_key = match.group(1).strip()
        content = match.group(2)
        if lang_key == "中文 (繁體)": lang_key = "中文"
        if lang_key == "Bahasa Indonesia": lang_key = "Indonesia"
        
        slogan_m = re.search(r"THUMBNAIL SLOGAN:\s*(.*)", content, re.IGNORECASE)
        if slogan_m:
            slogans[lang_key] = slogan_m.group(1).strip().strip('"')
            
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("===") or line.startswith("---"):
            continue
        if ":" in line:
            parts = line.split(":", 1)
            pre_colon = parts[0].strip()
            slogan_text = parts[1].strip().strip('"')
            if not slogan_text or pre_colon.upper() in ["TITLE", "DESCRIPTION", "TAGS", "BOOK_NAME", "IMAGE PROMPT", "BACKGROUND PROMPT"]:
                continue
            
            match = re.search(r'\((.*?)\)', pre_colon)
            extracted_key = match.group(1).strip() if match else pre_colon
            extracted_key = extracted_key.replace("NextRead", "").strip()
            if "中文" in extracted_key: extracted_key = "中文"
            elif "Indonesia" in extracted_key: extracted_key = "Indonesia"
                
            for kl in LANGUAGE_FOLDERS:
                if kl.lower() == extracted_key.lower() or kl.lower() in extracted_key.lower():
                    slogans[kl] = slogan_text
                    break
                    
    return slogans

def extract_book_name(ai_content):
    """ai_output.txt থেকে Book_Name: এর মান বের করে"""
    m = re.search(r"Book_Name:\s*(.*)", ai_content, re.IGNORECASE)
    if m:
        val = m.group(1).strip().strip('"').strip("'")
        val = val.splitlines()[0].strip()
        if val:
            return val
            
    # ব্যাকআপ হিসেবে যদি Book_Name না লিখে সরাসরি TITLE: লেখা থাকে
    m2 = re.search(r"TITLE:\s*(.*)", ai_content, re.IGNORECASE)
    if m2:
        val = m2.group(1).strip().strip('"').strip("'")
        val = val.splitlines()[0].strip()
        if val:
            return val
    return ""

def load_and_prepare_prompt(workspace_dir, ai_content, default_prompt):
    """
    Prompt.txt থেকে টেমপ্লেট নিয়ে [Book_Name] কে ai_output.txt-এর আসল নাম দিয়ে রিপ্লেস করে
    """
    book_name = extract_book_name(ai_content)
    if book_name:
        print(f"[+] বইয়ের নাম শনাক্ত হয়েছে: '{book_name}'")
    else:
        print("[!] ai_output.txt-এ 'Book_Name:' পাওয়া যায়নি। ডিফল্ট নাম ব্যবহৃত হবে।")

    # Prompt.txt ফাইলটি খোঁজা (রিপোজিটরি রুট অথবা Workspace ফোল্ডারে)
    prompt_file_candidates = [
        "Prompt.txt",
        os.path.join(workspace_dir, "Prompt.txt")
    ]
    
    prompt_template = None
    for p in prompt_file_candidates:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                txt = f.read().strip()
                if txt:
                    prompt_template = txt
                    print(f"[+] '{p}' ফাইল থেকে প্রম্পট টেমপ্লেট লোড হয়েছে।")
                    break

    if not prompt_template:
        print("[*] Prompt.txt পাওয়া যায়নি। config.json-এর ডিফল্ট প্রম্পট ব্যবহৃত হবে।")
        prompt_template = default_prompt

    # [Book_Name] বা {Book_Name} রিপ্লেসমেন্ট লজিক
    pattern = re.compile(r"\[Book_Name\]|\{Book_Name\}|<Book_Name>", re.IGNORECASE)
    if book_name:
        final_prompt = pattern.sub(book_name, prompt_template)
    else:
        final_prompt = pattern.sub("a bestselling book", prompt_template)

    return final_prompt

def generate_background_via_pollinations(prompt, output_file):
    print(f"[*] Pollinations.ai (FLUX) দিয়ে ব্যাকগ্রাউন্ড ইমেজ তৈরি শুরু হচ্ছে...")
    print(f"    চূড়ান্ত প্রম্পট: \"{prompt}\"")
    
    clean_prompt = prompt.strip()
    encoded_prompt = urllib.parse.quote(clean_prompt)
    seed = random.randint(1000, 999999)
    
    # Pollinations FLUX Engine (1920x1080 16:9)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1920&height=1080&model=flux&nologo=true&seed={seed}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for attempt in range(1, 4):
        try:
            print(f"    রিকোয়েস্ট পাঠানো হচ্ছে (চেষ্টা: {attempt}/3)...")
            res = requests.get(url, headers=headers, timeout=90)
            if res.status_code == 200 and len(res.content) > 5000:
                with open(output_file, "wb") as f:
                    f.write(res.content)
                print(f"[+] এআই ব্যাকগ্রাউন্ড সফলভাবে তৈরি হয়েছে এবং সেভ হয়েছে: {output_file}")
                return True
            else:
                print(f"    [!] স্ট্যাটাস কোড: {res.status_code}. ৫ সেকেন্ড পর রিট্রাই হবে...")
        except Exception as e:
            print(f"    [!] কানেকশন এরর: {e}")
        time.sleep(5)

    # ফলব্যাক: টার্বো মডেলে একবার চেষ্টা
    try:
        print("    [!] FLUX মডেল ব্যস্ত, বিকল্প মডেলে চেষ্টা করা হচ্ছে...")
        fallback_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1920&height=1080&nologo=true&seed={seed}"
        res = requests.get(fallback_url, headers=headers, timeout=60)
        if res.status_code == 200 and len(res.content) > 5000:
            with open(output_file, "wb") as f:
                f.write(res.content)
            print(f"[+] ফলব্যাক মডেলে ব্যাকগ্রাউন্ড তৈরি সফল হয়েছে!")
            return True
    except Exception as e:
        print(f"[-] বিকল্প জেনারেশনও ব্যর্থ: {e}")

    return False

def load_configuration(config_path):
    cfg = {
        'auto_generate_background': True,
        'default_background_prompt': "A cinematic dark aesthetic scene representing '[Book_Name]', open glowing book on a wooden desk, soft ambient lighting, library atmosphere, professional photography, hyperrealistic, 8k",
        'top_color': '#FFFFFF',
        'use_top_bg': False,
        'top_bg_color': '#000000',
        'bottom_color': '#FFFFFF',
        'use_bottom_bg': True,
        'bottom_bg_color': '#FF0000',
        'text_position': 'Center Right',
        'use_fixed_position': False,
        'is_compact': False,
        'spacing_1_2': 50,
        'line_spacing': 50,
        'add_audiobook_text': True,
        'audiobook_color': '#FFFFFF',
        'use_audiobook_bg': True,
        'audiobook_bg_color': '#000000',
        'audiobook_font_size': 45,
        'audiobook_spacing': 40
    }
    
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_cfg = json.load(f)
            for k, v in user_cfg.items():
                if isinstance(v, dict):
                    for sub_k, sub_v in v.items():
                        cfg[sub_k] = sub_v
                else:
                    cfg[k] = v
            print(f"[+] config.json সেটিংস সফলভাবে লোড হয়েছে।")
        except Exception as e:
            print(f"[!] সতর্কতা: config.json পার্স করা যায়নি ({e})। ডিফল্ট ব্যবহৃত হবে।")
    return cfg

def render_thumbnail(background_image, full_text, detected_folder, font_path, output_path, appearance_settings, layout_settings):
    engine_layout_lang = get_ot_lang_tag(detected_folder)
    should_apply_stroke = (detected_folder not in ['বাংলা', 'हिन्दी', 'العربية'])

    img_copy = background_image.copy()
    draw = ImageDraw.Draw(img_copy)
    bg_w, bg_h = img_copy.size
    panel_margin = 60

    if layout_settings.get('is_compact', False):
        text_lines = split_text_compactly(full_text)
    else:
        text_lines = split_text_smartly(full_text)

    if not text_lines:
        return False

    panel_location = layout_settings['panel_location']
    v_align_override = "Fixed" if layout_settings.get('use_fixed_position', False) else layout_settings['v_align']

    if panel_location == "Left": 
        panel_x_start, panel_width = 0, int(bg_w * (1 - TEXT_PANEL_START_X_RATIO))
    elif panel_location == "Right": 
        panel_x_start, panel_width = int(bg_w * TEXT_PANEL_START_X_RATIO), bg_w - int(bg_w * TEXT_PANEL_START_X_RATIO)
    else: 
        panel_x_start, panel_width = 0, bg_w

    target_text_width = panel_width - (2 * panel_margin)
    line_fonts, line_heights, line_widths = [], [], []
    for idx, text_line in enumerate(text_lines):
        shaping_optimized = fix_complex_scripts(text_line, detected_folder)
        max_size = 250 if len(text_lines) == 1 else (200 if idx == 0 else 220)
        font = get_optimal_font(draw, shaping_optimized, font_path, target_text_width, max_size, engine_lang=engine_layout_lang)
        
        bkwargs = {} if not engine_layout_lang else {'language': engine_layout_lang}
        bbox = robust_bbox_and_draw('bbox', draw, shaping_optimized, font, (0,0), bkwargs, False)
        line_fonts.append(font)
        line_heights.append(bbox[3] - bbox[1])
        line_widths.append(bbox[2] - bbox[0])

    spacing_1_2 = layout_settings.get('spacing_1_2', 50)
    spacing_subsequent = layout_settings.get('line_spacing', 50)

    total_text_height = sum(line_heights)
    if len(text_lines) > 1: total_text_height += spacing_1_2
    if len(text_lines) > 2: total_text_height += spacing_subsequent * (len(text_lines) - 2)

    margin = 50
    if v_align_override == "Top": y_cursor = margin
    elif v_align_override == "Bottom": y_cursor = bg_h - total_text_height - margin
    elif v_align_override == "Fixed": y_cursor = (bg_h * 0.35) - (total_text_height / 2)
    else: y_cursor = (bg_h - total_text_height) / 2

    for idx, text_line in enumerate(text_lines):
        fixed_out_txt = fix_complex_scripts(text_line, detected_folder)
        settings_key = 'top' if idx == 0 else 'bottom'
        font, width = line_fonts[idx], line_widths[idx]
        x_pos = panel_x_start + (panel_width - width) / 2
        draw_text_with_optional_bg(draw, fixed_out_txt, font, settings_key, x_pos, y_cursor, appearance_settings, engine_lang=engine_layout_lang, apply_stroke=should_apply_stroke)
        
        spacing_to_add = 0
        if idx < len(text_lines) - 1:
            spacing_to_add = spacing_1_2 if idx == 0 else spacing_subsequent
        y_cursor += line_heights[idx] + spacing_to_add

    # Audiobook badge
    if appearance_settings.get('add_audiobook_text', False):
        audio_text = "Audiobook Podcast"
        try:
            font_size = appearance_settings.get('audiobook_font_size', 45)
            audio_font = ImageFont.truetype(font_path, size=font_size)
        except Exception:
            audio_font = ImageFont.load_default()
            
        akwargs = {'language': 'en'}
        bbox = robust_bbox_and_draw('bbox', draw, audio_text, audio_font, (0,0), akwargs, False)
        x_pos = panel_x_start + (panel_width - (bbox[2] - bbox[0])) / 2
        y_pos = y_cursor + layout_settings.get('audiobook_spacing', 40)
        draw_text_with_optional_bg(draw, audio_text, audio_font, 'audiobook', x_pos, y_pos, appearance_settings, engine_lang='en', apply_stroke=False)

    buffer = io.BytesIO()
    final_image = img_copy.convert("RGB")
    final_image.save(buffer, format="JPEG", quality=95)
    if buffer.getbuffer().nbytes > TARGET_MAX_BYTES:
        for q in range(90, 10, -5):
            buffer = io.BytesIO()
            final_image.save(buffer, format="JPEG", quality=q)
            if buffer.getbuffer().nbytes <= TARGET_MAX_BYTES:
                break

    with open(output_path, "wb") as f:
        f.write(buffer.getvalue())
    return True

def main():
    parser = argparse.ArgumentParser(description="Automated Headless Thumbnail Generator")
    parser.add_argument("--workspace", default="./Workspace", help="Workspace folder")
    parser.add_argument("--config", default="./config.json", help="Path to config.json")
    parser.add_argument("--fonts_dir", default=None, help="Directory containing fonts")
    args = parser.parse_args()

    workspace_dir = os.path.abspath(args.workspace)
    if not os.path.exists(workspace_dir):
        print(f"[-] Error: Workspace ফোল্ডার পাওয়া যায়নি: '{workspace_dir}'")
        return

    cfg = load_configuration(args.config)

    # ai_output.txt ফাইল পড়া
    ai_txt_path = os.path.join(workspace_dir, "ai_output.txt")
    ai_content = ""
    if os.path.exists(ai_txt_path):
        with open(ai_txt_path, "r", encoding="utf-8") as f:
            ai_content = f.read()

    # ১. Background.png ফাইল চেক
    bg_candidates = ["Background.png", "background.png", "Background.jpg", "background.jpg", "Background.jpeg", "background.jpeg"]
    bg_path = None
    for c in bg_candidates:
        candidate_path = os.path.join(workspace_dir, c)
        if os.path.exists(candidate_path):
            bg_path = candidate_path
            break

    # ড্রাইভে ছবি না থাকলে Prompt.txt + [Book_Name] রিপ্লেস করে AI ব্যাকগ্রাউন্ড তৈরি
    if not bg_path and cfg.get('auto_generate_background', True):
        prompt = load_and_prepare_prompt(workspace_dir, ai_content, cfg.get('default_background_prompt'))
        auto_bg_path = os.path.join(workspace_dir, "Background.png")
        if generate_background_via_pollinations(prompt, auto_bg_path):
            bg_path = auto_bg_path

    if not bg_path:
        print(f"[!] তথ্য: '{workspace_dir}' ফোল্ডারে কোনো 'Background.png' পাওয়া যায়নি এবং জেনারেটও করা যায়নি।")
        print("    স্বয়ংক্রিয় ব্যাকগ্রাউন্ড জেনারেশন স্কিপ করা হচ্ছে।")
        return

    print(f"[+] মূল ব্যাকগ্রাউন্ড ছবি প্রস্তুত: {bg_path}")
   
