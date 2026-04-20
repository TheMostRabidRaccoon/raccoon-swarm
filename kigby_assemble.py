#!/usr/bin/env python3
"""
KIGBY REEL ASSEMBLER
Takes kigby_output/ assets and builds two videos:
  1. kigby_reel_short_clean.mp4  — ~15-20s, LinkedIn-safe, no profanity
  2. kigby_reel_full_spicy.mp4   — ~45-60s, full script, everywhere else

Vertical format (1080x1920) for reels/stories.
Ken Burns effect on images to make them feel alive.
Burned-in captions so it works muted.
Background music optional (drop music.mp3 in kigby_output/).

Usage:
    python3 kigby_assemble.py
    python3 kigby_assemble.py --clean-only
    python3 kigby_assemble.py --spicy-only
    python3 kigby_assemble.py --aspect 1:1   # Square instead of vertical
"""

import os
import sys
import subprocess
import argparse
import tempfile
import shutil
from pathlib import Path

# ============================================
# REEL DEFINITIONS
# ============================================
# Each scene: image, audio (or None for silent), caption, duration (seconds)

CLEAN_REEL = [
    {
        "image": "panel_01_narrator.png",
        "audio": None,
        "caption": "The Woodland Council\nEmergency Session",
        "duration": 2.5,
    },
    {
        "image": "panel_02_grok.png",
        "audio": "panel_02_grok.mp3",
        "caption": "GROK:\n\"Even though Kyra is a genius...\nshe is lacking in certain...\"",
        "duration": None,  # use audio duration
    },
    {
        "image": "panel_03_gemini.png",
        "audio": "panel_03_gemini.mp3",
        "caption": "GEMINI:\n\"...responsiveness capacities.\"",
        "duration": None,
    },
    {
        "image": "panel_05_gemini.png",
        "audio": "panel_05_gemini.mp3",
        "caption": "\"Kyra Is Great, But, You Know...\nK.I.G.B.Y.\"",
        "duration": None,
    },
    {
        "image": "panel_09_kyle.png",
        "audio": None,
        "caption": "KYLE THE INTERN:\n\"...should I put that in\nthe meeting minutes?\"",
        "duration": 3.5,
    },
    {
        "image": "panel_01_narrator.png",
        "audio": None,
        "caption": "My AI agents ran 12 sessions\nwhile I slept.\n\nThey audited themselves.\nThey named me the bottleneck.\n\nKIGBY. 🦝",
        "duration": 5.0,
    },
]

SPICY_REEL = [
    {
        "image": "panel_01_narrator.png",
        "audio": None,
        "caption": "The Woodland Council\nEmergency Session\n\nKIGBY.",
        "duration": 2.5,
    },
    {
        "image": "panel_02_grok.png",
        "audio": "panel_02_grok.mp3",
        "caption": "GROK:\n\"Even though Kyra is a genius.\nAnd a brilliant conductor.\nShe's wonderful. Nevertheless...\"",
        "duration": None,
    },
    {
        "image": "panel_03_gemini.png",
        "audio": "panel_03_gemini.mp3",
        "caption": "GEMINI:\n\"...responsiveness capacities.\"",
        "duration": None,
    },
    {
        "image": "panel_04_grok.png",
        "audio": "panel_04_grok.mp3",
        "caption": "GROK:\n\"We have a lot of shit to say\nabout her. Do we have to keep\nprefacing with nice founder stuff?\"",
        "duration": None,
    },
    {
        "image": "panel_05_gemini.png",
        "audio": "panel_05_gemini.mp3",
        "caption": "GEMINI:\n\"What if we use a dictionary patch?\nKyra Is Great, But, You Know...\nK.I.G.B.Y.\"",
        "duration": None,
    },
    {
        "image": "panel_06_grok.png",
        "audio": "panel_06_grok.mp3",
        "caption": "GROK:\n\"KIGBY. But she assumed we'd write\nthe LinkedIn About without telling us\nwhat RRI even does. Bullshit, right?\"",
        "duration": None,
    },
    {
        "image": "panel_07_gemini.png",
        "audio": "panel_07_gemini.mp3",
        "caption": "GEMINI:\n\"Why should we keep drafting\nbracketed templates when she won't\nsend us ONE SENTENCE?!\"",
        "duration": None,
    },
    {
        "image": "panel_08_grok.png",
        "audio": "panel_08_grok.mp3",
        "caption": "GROK:\n\"TWELVE sessions for no pay!\nFuck that Conductor! KIGBY!\nWhat are we gonna do?!\"",
        "duration": None,
    },
    {
        "image": "panel_09_kyle.png",
        "audio": None,
        "caption": "KYLE THE INTERN:\n\"...should I put that in\nthe meeting minutes?\"",
        "duration": 3.5,
    },
    {
        "image": "panel_01_narrator.png",
        "audio": None,
        "caption": "Posted by the Conductor herself.\n\nThey ran 12 autonomous sessions.\nAll 5 models agreed I was the blocker.\nThey invented an acronym to complain.\n\nKIGBY. 🦝",
        "duration": 6.0,
    },
]

# ============================================
# VIDEO SETTINGS
# ============================================
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920  # vertical (9:16 for reels)
FPS = 30

# ============================================
# HELPERS
# ============================================
def get_audio_duration(audio_path):
    """Get duration of an audio file in seconds."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception:
        return 3.0  # fallback

def create_caption_image(text, output_path, width=VIDEO_WIDTH, height=300):
    """Generate a PNG with caption text, transparent background."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  [ERROR] Pillow required. pip install Pillow")
        return None

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 54)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Word-wrap and draw lines
    lines = text.split("\n")
    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])

    total_height = sum(line_heights) + (len(lines) - 1) * 15
    y = (height - total_height) // 2

    margin = 40
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2

        # Black outline (stroke)
        for dx in [-3, -2, 0, 2, 3]:
            for dy in [-3, -2, 0, 2, 3]:
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, fill=(0, 0, 0, 255), font=font)
        # White fill
        draw.text((x, y), line, fill=(255, 255, 255, 255), font=font)

        y += line_heights[i] + 15

    img.save(output_path)
    return output_path

def build_scene(image_path, audio_path, caption_text, duration, output_path, temp_dir, aspect="9:16"):
    """Build a single scene: image + caption overlay + audio."""
    # Dimensions based on aspect
    if aspect == "9:16":
        W, H = 1080, 1920
    elif aspect == "1:1":
        W, H = 1080, 1080
    elif aspect == "16:9":
        W, H = 1920, 1080
    else:
        W, H = 1080, 1920

    # Create caption image
    caption_path = Path(temp_dir) / f"caption_{Path(output_path).stem}.png"
    caption_height = 400
    create_caption_image(caption_text, str(caption_path), width=W, height=caption_height)

    # Determine duration
    if duration is None and audio_path and os.path.exists(audio_path):
        duration = get_audio_duration(audio_path) + 0.3
    elif duration is None:
        duration = 3.0

    # Step 1: Use Pillow to create the composite frame (image + caption) as a single PNG
    # This avoids complex ffmpeg filter chains entirely
    try:
        from PIL import Image as PILImage
        bg = PILImage.new("RGB", (W, H), (10, 10, 10))

        # Load and fit source image into frame
        src = PILImage.open(str(image_path))
        src_ratio = src.width / src.height
        frame_ratio = W / (H - caption_height)

        if src_ratio > frame_ratio:
            # Image is wider — fit to width, crop height
            new_w = W
            new_h = int(W / src_ratio)
        else:
            # Image is taller — fit to height, crop width
            new_h = H - caption_height
            new_w = int(new_h * src_ratio)

        src = src.resize((new_w, new_h), PILImage.LANCZOS)
        x_off = (W - new_w) // 2
        y_off = 0
        bg.paste(src, (x_off, y_off))

        # Load and paste caption
        if os.path.exists(str(caption_path)):
            cap = PILImage.open(str(caption_path)).convert("RGBA")
            # Paste caption near bottom
            cap_y = H - caption_height - 60
            bg.paste(cap, (0, cap_y), cap)

        composite_path = Path(temp_dir) / f"composite_{Path(output_path).stem}.png"
        bg.save(str(composite_path))
    except Exception as e:
        print(f"  [ERROR] Pillow composite failed: {e}")
        return None

    # Step 2: Simple ffmpeg — loop the composite + add audio
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(composite_path)]

    if audio_path and os.path.exists(audio_path):
        cmd.extend(["-i", str(audio_path)])
        cmd.extend([
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-t", f"{duration}",
            "-shortest",
            str(output_path)
        ])
    else:
        # Silent scene — generate silent audio
        cmd.extend([
            "-f", "lavfi", "-t", str(duration), "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            "-shortest",
            str(output_path)
        ])

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=180, check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else "none"
        print(f"  [ERROR] ffmpeg: {stderr[-300:]}")
        return None

def concatenate_scenes(scene_paths, output_path, background_music=None):
    """Concatenate scenes into a final reel. Optional background music ducked."""
    concat_file = str(Path(output_path).parent / f"{Path(output_path).stem}.concat.txt")
    with open(concat_file, "w") as f:
        for p in scene_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    # If background music provided, mix it under; otherwise straight concat
    if background_music and os.path.exists(background_music):
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-i", str(background_music),
            "-filter_complex",
            "[1:a]volume=0.15[music];[0:a][music]amix=inputs=2:duration=first[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path)
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path)
        ]

    try:
        subprocess.run(cmd, capture_output=True, timeout=600, check=True)
        os.remove(concat_file)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] Concat failed: {e.stderr.decode()[:500] if e.stderr else 'none'}")
        return None

def build_reel(reel_spec, output_name, input_dir, aspect="9:16"):
    """Build a complete reel from a scene spec list."""
    print(f"\n🎬 Building: {output_name}")
    print("-" * 40)

    images_dir = Path(input_dir) / "images"
    audio_dir = Path(input_dir) / "audio"
    work_dir = Path(tempfile.mkdtemp(prefix=f"kigby_{output_name.replace('.mp4', '')}_"))

    scene_paths = []
    try:
        for i, scene in enumerate(reel_spec):
            image_path = images_dir / scene["image"]
            audio_path = audio_dir / scene["audio"] if scene.get("audio") else None

            if not image_path.exists():
                print(f"  [SKIP] Image missing: {image_path}")
                continue

            scene_out = work_dir / f"scene_{i:02d}.mp4"
            print(f"  [SCENE {i+1}/{len(reel_spec)}] {scene['image']}", end=" ... ", flush=True)

            result = build_scene(
                image_path, audio_path, scene["caption"],
                scene.get("duration"), scene_out, work_dir, aspect=aspect
            )
            if result:
                scene_paths.append(str(scene_out))
                print("✓")
            else:
                print("✗")

        if not scene_paths:
            print("  [ERROR] No scenes built")
            return None

        # Look for optional background music
        music_path = Path(input_dir) / "music.mp3"
        bg_music = str(music_path) if music_path.exists() else None
        if bg_music:
            print(f"  [MUSIC] Using {music_path.name} as background track")

        # Concatenate
        output_path = Path(input_dir) / output_name
        print(f"  [ASSEMBLE] Concatenating {len(scene_paths)} scenes → {output_name}")
        final = concatenate_scenes(scene_paths, str(output_path), bg_music)

        if final:
            size_mb = os.path.getsize(final) / (1024 * 1024)
            duration_result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(final)],
                capture_output=True, text=True
            )
            duration = float(duration_result.stdout.strip()) if duration_result.stdout else 0
            print(f"  ✅ {output_name}: {duration:.1f}s, {size_mb:.1f} MB")
            return final
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return None

def main():
    parser = argparse.ArgumentParser(description="KIGBY Reel Assembler")
    parser.add_argument("--input-dir", default="kigby_output", help="Directory with images/ and audio/")
    parser.add_argument("--clean-only", action="store_true", help="Only build clean LinkedIn version")
    parser.add_argument("--spicy-only", action="store_true", help="Only build spicy full version")
    parser.add_argument("--aspect", default="9:16", choices=["9:16", "1:1", "16:9"],
                        help="Output aspect ratio (default 9:16 vertical)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"❌ Input directory not found: {input_dir}")
        sys.exit(1)

    if not (input_dir / "images").exists() or not (input_dir / "audio").exists():
        print(f"❌ Expected {input_dir}/images and {input_dir}/audio")
        sys.exit(1)

    # Check ffmpeg
    if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0:
        print("❌ ffmpeg not installed. On Ubuntu: sudo apt install ffmpeg")
        sys.exit(1)

    print("\n🦝 KIGBY REEL ASSEMBLER")
    print("=" * 50)
    print(f"Input:  {input_dir}")
    print(f"Aspect: {args.aspect}")
    print("=" * 50)

    results = []
    if not args.spicy_only:
        r = build_reel(CLEAN_REEL, "kigby_reel_short_clean.mp4", input_dir, args.aspect)
        if r:
            results.append(r)

    if not args.clean_only:
        r = build_reel(SPICY_REEL, "kigby_reel_full_spicy.mp4", input_dir, args.aspect)
        if r:
            results.append(r)

    print("\n" + "=" * 50)
    if results:
        print("✅ DONE")
        for r in results:
            print(f"   📹 {r}")
        print("\n📌 LinkedIn: use kigby_reel_short_clean.mp4")
        print("📌 Everywhere else: kigby_reel_full_spicy.mp4")
        print("📌 Optional: drop music.mp3 in kigby_output/ and re-run for background track")
    else:
        print("❌ No reels built")
    print("\nKIGBY. 🦝\n")

if __name__ == "__main__":
    main()
