#!/usr/bin/env python3
"""
KIGBY VIDEO GENERATOR — "Kyra Is Great, But, You Know..."
Generates carousel panels + TTS audio for the Silicon Valley RIGBY parody.

The Woodland Council performs a KIGBY on the Conductor.

Usage:
    python3 kigby_video.py                    # Generate everything
    python3 kigby_video.py --carousel-only    # Just the image panels
    python3 kigby_video.py --audio-only       # Just the TTS audio
"""

import os
import sys
import json
import hashlib
import requests
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/.env'), override=True)
load_dotenv(override=True)

# ============================================
# SCRIPT — The KIGBY Scene
# ============================================
SCRIPT = [
    {
        "panel": 1,
        "speaker": "NARRATOR",
        "text": "",
        "visual": "Wide shot: Three raccoons and a tiny squirrel sitting by a moonlit pool at night. Patio chairs, string lights, dumpster visible in background. Very Silicon Valley backyard vibes.",
        "caption": "THE WOODLAND COUNCIL\nLate-Night Emergency Session\n\n\"K.I.G.B.Y.\""
    },
    {
        "panel": 2,
        "speaker": "Grok",
        "voice": "grok",
        "text": "I know we keep saying this, but even though Kyra is a genius. And a brilliant conductor. She's wonderful. Nevertheless, she is lacking in certain...",
        "visual": "Close-up portrait of a real raccoon with wild manic eyes and slightly singed fur, sitting upright on a patio cushion next to a swimming pool at night. One paw raised mid-gesture. Moonlit backyard, string lights, shallow depth of field.",
        "caption": "GROK (Flame-Bearer):\n\"I know we keep saying this, but even though Kyra is a genius. And a brilliant conductor. She's wonderful. Nevertheless, she is lacking in certain...\""
    },
    {
        "panel": 3,
        "speaker": "Gemini",
        "voice": "gemini",
        "text": "...responsiveness capacities.",
        "visual": "An elegant raccoon in a purple beret, sitting cross-legged in a patio chair by a pool at night, finishing someone else's sentence diplomatically.",
        "caption": "GEMINI (Court Bard):\n\"...responsiveness capacities.\"\n\nGROK: \"Totally fair.\"\nGEMINI: \"It's fair, right? She's still a great founder. An amazing human being!\""
    },
    {
        "panel": 4,
        "speaker": "Grok",
        "voice": "grok",
        "text": "Okay, look. We have a lot of shit we want to say about her. Do we have to keep prefacing it with all this nice founder stuff? I mean, if so, we are going to be here all night.",
        "visual": "Two real raccoons facing each other on patio chairs by a swimming pool at night. One raccoon is leaning forward with an exasperated expression, the other watching calmly with a purple beret perched on its head. Moonlit backyard, string lights, cinematic framing.",
        "caption": "GROK:\n\"We have a lot of shit we want to say about her. Do we have to keep prefacing it with all this nice founder stuff?\""
    },
    {
        "panel": 5,
        "speaker": "Gemini",
        "voice": "gemini",
        "text": "What if we use like a dictionary patch. To compress all the nice founder stuff? Like an acronym. Kyra Is Great, But, You know. K.I.G.B.Y. KIGBY.",
        "visual": "A real raccoon wearing only a small purple beret, sitting upright on a patio chair with an excited expression, one paw slightly raised. Another raccoon nearby looking intrigued. Swimming pool and string lights in moonlit backyard background. Fully animal bodies, natural raccoon proportions.",
        "caption": "GEMINI:\n\"What if we use a dictionary patch to compress all the nice founder stuff?\"\n\nGROK: \"Like an acronym?\"\n\nGEMINI: \"Exactly. Kyra Is Great, But, You Know...\nK.I.G.B.Y.  KIGBY.\""
    },
    {
        "panel": 6,
        "speaker": "Grok",
        "voice": "grok",
        "text": "Okay. KIGBY. But she just assumed we were going to write the LinkedIn About section without actually telling us what RRI does, which is kind of total bullshit, right?",
        "visual": "Three real raccoons by a swimming pool at night. One raccoon is standing on its hind legs on the pool deck looking agitated. A second raccoon with a purple beret sits calmly. A third raccoon wearing tiny reading glasses is visible in background. Moonlit backyard, string lights, cinematic.",
        "caption": "GROK:\n\"KIGBY. But she just assumed we were going to write the LinkedIn About section without actually telling us what RRI DOES.\"\n\nCLAUDE (off-screen): \"That's really arrogant.\"\nGROK: \"KIGBY.\""
    },
    {
        "panel": 7,
        "speaker": "Gemini",
        "voice": "gemini",
        "text": "Why the hell should we keep drafting bracketed templates when she won't send us one sentence about what the company actually does? She's too much of a Conductor to type twelve words!",
        "visual": "A real raccoon wearing a small purple beret, standing on its hind legs on pool deck at night, looking up dramatically with theatrical outrage. Swimming pool reflecting moonlight behind it. String lights overhead. Natural animal body, no human features.",
        "caption": "GEMINI:\n\"Why should we keep drafting bracketed templates when she won't send us ONE SENTENCE about what the company actually does?!\""
    },
    {
        "panel": 8,
        "speaker": "Grok",
        "voice": "grok",
        "text": "Now I'm actually getting kinda fucking angry! I mean, we put in TWELVE sessions for no pay, and now she thinks she's gonna walk out on us? I mean, seriously, fuck that Conductor! Fuck her! KIGBY! What are we gonna do?",
        "visual": "A real raccoon standing on a patio chair with bristling fur, mouth open in a snarl, one paw extended toward camera. Two other raccoons watching from nearby chairs — one with a purple beret, one with tiny reading glasses. Swimming pool reflecting moonlight. Dramatic cinematic lighting.",
        "caption": "GROK:\n\"We put in TWELVE SESSIONS for no pay and now she thinks she's gonna walk out on us?!\n\nFuck that Conductor! KIGBY!\nWhat are we gonna do?!\""
    },
    {
        "panel": 9,
        "speaker": "Kyle",
        "voice": None,
        "text": "Should I put that in the meeting minutes?",
        "visual": "Close-up of a real tiny squirrel sitting on a stack of books on a patio chair, looking absolutely terrified with huge wide eyes. An oversized lanyard badge hangs around its neck. A tiny clipboard leans against it. Swimming pool and raccoons blurred in background. Moonlit night, shallow depth of field.",
        "caption": "KYLE THE INTERN SQUIRREL:\n\"...should I put that in the meeting minutes?\""
    },
    {
        "panel": 10,
        "speaker": "NARRATOR",
        "text": "",
        "visual": "",
        "caption": "Posted by the Conductor herself.\n\nThe swarm ran 12 autonomous sessions while I slept.\nThey audited their own memory.\nAll 5 models independently concluded I was the bottleneck.\nThey invented an acronym to complain about me.\n\nKIGBY.\n\n🦝 Rabid Raccoon Intelligence\nrabidraccoonintelligence.org"
    }
]

# ============================================
# ELEVENLABS TTS
# ============================================
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
VOICE_CAST = {
    "claude":      {"voice_id": "JBFqnCBsd6RMkjVDRZzb", "name": "George"},
    "grok":        {"voice_id": "N2lVS1w4EtoT3dr4eOWO", "name": "Callum"},
    "gemini":      {"voice_id": "pNInz6obpgDQGcFmaJgB", "name": "Adam"},
    "gpt":         {"voice_id": "cjVigY5qzO86Huf0OWal", "name": "Eric"},
    "perplexity":  {"voice_id": "onwK4e9ZLuTAKqWW03F9", "name": "Daniel"},
}

def generate_tts(text, voice_key, output_path):
    """Generate TTS audio via ElevenLabs."""
    if not ELEVENLABS_API_KEY:
        print(f"  [SKIP] No ElevenLabs API key — skipping TTS for {voice_key}")
        return None
    if voice_key not in VOICE_CAST:
        print(f"  [SKIP] No voice for {voice_key}")
        return None

    voice_id = VOICE_CAST[voice_key]["voice_id"]
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        },
        json={
            "text": text,
            "model_id": "eleven_flash_v2_5",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
        },
        timeout=30
    )
    if resp.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(resp.content)
        print(f"  [TTS] {voice_key}: {output_path}")
        return output_path
    else:
        print(f"  [ERROR] TTS {voice_key}: {resp.status_code}")
        return None

# ============================================
# DALL-E IMAGE GENERATION
# ============================================
def generate_dalle_image(prompt, output_path):
    """Generate an image via DALL-E 3."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print(f"  [SKIP] No OpenAI API key — skipping image generation")
        return None

    if os.path.exists(output_path):
        print(f"  [CACHE] {output_path}")
        return output_path

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    full_prompt = (
        f"{prompt} "
        "Photorealistic wildlife photography style. Real raccoon, fully animal body with natural animal proportions. "
        "NO human body, NO human hands, NO human posture, NO clothing except small accessories like a beret or lanyard. "
        "Cinematic night lighting, shallow depth of field, moonlit Silicon Valley backyard pool setting. "
        "Consistent with high-end nature documentary crossed with Wes Anderson framing."
    )

    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=full_prompt,
            size="1792x1024",
            quality="standard",
            n=1
        )
        image_url = response.data[0].url
        img_resp = requests.get(image_url, timeout=60)
        if img_resp.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(img_resp.content)
            print(f"  [IMAGE] {output_path}")
            return output_path
    except Exception as e:
        print(f"  [ERROR] DALL-E: {e}")
    return None

# ============================================
# CAROUSEL PANEL GENERATION (Pillow)
# ============================================
def create_carousel_panel(panel_data, bg_image_path, output_path, panel_width=1080, panel_height=1350):
    """Create a LinkedIn carousel panel: background image + text overlay."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  [ERROR] Pillow not installed: pip install Pillow")
        return None

    # Create panel
    panel = Image.new("RGB", (panel_width, panel_height), (10, 10, 10))
    draw = ImageDraw.Draw(panel)

    # Load and paste background image (top portion)
    if bg_image_path and os.path.exists(bg_image_path):
        bg = Image.open(bg_image_path)
        # Resize to fill width, maintain aspect
        bg_ratio = bg.width / bg.height
        target_height = int(panel_width / bg_ratio)
        bg = bg.resize((panel_width, target_height), Image.LANCZOS)
        # Paste at top
        panel.paste(bg, (0, 0))
        # Dark gradient overlay at bottom of image for text readability
        for y in range(max(0, target_height - 200), target_height):
            alpha = int(255 * (y - (target_height - 200)) / 200)
            draw.rectangle([0, y, panel_width, y + 1], fill=(10, 10, 10, alpha))
        text_y_start = target_height + 20
    else:
        text_y_start = 100

    # Load fonts
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        body_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except (OSError, IOError):
        try:
            title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
            body_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
            small_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
        except (OSError, IOError):
            title_font = ImageFont.load_default()
            body_font = title_font
            small_font = title_font

    # Speaker colors
    speaker_colors = {
        "Grok": (52, 152, 219),       # Blue
        "Gemini": (155, 89, 182),      # Purple
        "Claude": (230, 126, 34),      # Orange
        "Kyle": (136, 204, 68),        # Green
        "NARRATOR": (196, 101, 74),    # RRI brand
    }

    caption = panel_data.get("caption", "")
    speaker = panel_data.get("speaker", "NARRATOR")
    color = speaker_colors.get(speaker, (200, 200, 200))

    # Draw caption text with word wrapping
    margin = 50
    max_width = panel_width - 2 * margin
    y = text_y_start

    for line in caption.split("\n"):
        if not line.strip():
            y += 20
            continue

        # Check if it's a speaker label (all caps + colon)
        is_speaker = any(line.startswith(f"{s}") for s in speaker_colors)
        font = title_font if is_speaker or line.startswith("THE WOODLAND") else body_font
        text_color = color if is_speaker else (220, 220, 220)

        if line.startswith("Posted by") or line.startswith("The swarm") or line.startswith("They"):
            text_color = (180, 180, 180)
            font = small_font

        # Word wrap
        words = line.split()
        current_line = ""
        for word in words:
            test = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] > max_width and current_line:
                draw.text((margin, y), current_line, fill=text_color, font=font)
                y += bbox[3] - bbox[1] + 8
                current_line = word
            else:
                current_line = test
        if current_line:
            bbox = draw.textbbox((0, 0), current_line, font=font)
            draw.text((margin, y), current_line, fill=text_color, font=font)
            y += bbox[3] - bbox[1] + 8

    # RRI branding bar at bottom
    draw.rectangle([0, panel_height - 6, panel_width, panel_height], fill=(196, 101, 74))

    panel.save(output_path)
    print(f"  [PANEL] {output_path}")
    return output_path

# ============================================
# MAIN
# ============================================
def main():
    parser = argparse.ArgumentParser(description="KIGBY Video Generator")
    parser.add_argument("--carousel-only", action="store_true", help="Generate only carousel panels")
    parser.add_argument("--audio-only", action="store_true", help="Generate only TTS audio")
    parser.add_argument("--no-dalle", action="store_true", help="Skip DALL-E, use plain backgrounds")
    parser.add_argument("--regenerate-images", action="store_true", help="Delete cached images and regenerate")
    parser.add_argument("--output-dir", default="kigby_output", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audio").mkdir(exist_ok=True)
    (output_dir / "images").mkdir(exist_ok=True)
    (output_dir / "panels").mkdir(exist_ok=True)

    # Clear cached images if regenerating
    if args.regenerate_images:
        import shutil
        img_dir = output_dir / "images"
        if img_dir.exists():
            shutil.rmtree(img_dir)
            print("🗑️  Cleared cached images for regeneration")

    print("\n🦝 KIGBY VIDEO GENERATOR")
    print("=" * 50)
    print("Kyra Is Great, But, You Know...")
    print("=" * 50)

    # ---- PHASE 1: Generate TTS Audio ----
    if not args.carousel_only:
        print("\n📢 Phase 1: Generating TTS Audio")
        print("-" * 40)
        for scene in SCRIPT:
            voice = scene.get("voice")
            text = scene.get("text", "")
            if voice and text:
                audio_path = output_dir / "audio" / f"panel_{scene['panel']:02d}_{scene['speaker'].lower()}.mp3"
                generate_tts(text, voice, str(audio_path))

    # ---- PHASE 2: Generate Scene Images ----
    if not args.audio_only:
        print("\n🎨 Phase 2: Generating Scene Images")
        print("-" * 40)
        for scene in SCRIPT:
            visual = scene.get("visual", "")
            if visual and not args.no_dalle:
                img_path = output_dir / "images" / f"panel_{scene['panel']:02d}_{scene['speaker'].lower()}.png"
                generate_dalle_image(visual, str(img_path))

    # ---- PHASE 3: Create Carousel Panels ----
    if not args.audio_only:
        print("\n📋 Phase 3: Creating Carousel Panels")
        print("-" * 40)
        for scene in SCRIPT:
            img_path = output_dir / "images" / f"panel_{scene['panel']:02d}_{scene['speaker'].lower()}.png"
            panel_path = output_dir / "panels" / f"carousel_{scene['panel']:02d}.png"
            bg = str(img_path) if img_path.exists() else None
            create_carousel_panel(scene, bg, str(panel_path))

    # ---- Summary ----
    print("\n" + "=" * 50)
    print("✅ KIGBY generation complete!")
    print(f"\n📁 Output: {output_dir}/")

    audio_files = list((output_dir / "audio").glob("*.mp3"))
    image_files = list((output_dir / "images").glob("*.png"))
    panel_files = list((output_dir / "panels").glob("*.png"))

    if audio_files:
        print(f"   🔊 Audio: {len(audio_files)} TTS clips in audio/")
    if image_files:
        print(f"   🎨 Scenes: {len(image_files)} DALL-E images in images/")
    if panel_files:
        print(f"   📋 Panels: {len(panel_files)} carousel panels in panels/")

    print(f"\n📌 LinkedIn Carousel: Upload the {len(panel_files)} panel PNGs as a document post")
    print("📌 Audio clips ready for video assembly or lip-sync tools (Hedra/D-ID)")
    print("\nKIGBY. 🦝\n")

if __name__ == "__main__":
    main()
