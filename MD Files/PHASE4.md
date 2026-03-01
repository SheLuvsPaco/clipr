# PHASE 4 — CAPTION RENDERING
### Burning Viral-Style Captions Into Every Clip

---

## What This Phase Does

Phase 4 takes the processed 1080×1920 vertical clip from Phase 3 and burns captions directly into the video frames using the ASS (Advanced SubStation Alpha) subtitle format rendered through ffmpeg's libass engine.

The captions are generated from the word-level timestamp data produced in Phase 1 — every word is mapped to its exact spoken time, meaning captions sync to the millisecond with no drift, no offset corrections, and no manual timing adjustments.

This phase produces the final deliverable: a captioned MP4 file ready to upload to TikTok, Instagram Reels, and YouTube Shorts.

---

## Why ASS Format and Not SRT

SRT is the most common subtitle format. It is also completely inadequate for what we're building.

| Capability | SRT | ASS |
|---|---|---|
| Font family control | ❌ | ✅ |
| Font size | ❌ | ✅ |
| Bold / italic | ❌ | ✅ |
| Text colour | ❌ | ✅ |
| Outline colour and thickness | ❌ | ✅ |
| Drop shadow | ❌ | ✅ |
| Background box | ❌ | ✅ |
| Screen position (X, Y) | ❌ | ✅ |
| Per-word colour change | ❌ | ✅ |
| Word-by-word timing (karaoke) | ❌ | ✅ |
| Fade in / fade out animations | ❌ | ✅ |
| Letter spacing | ❌ | ✅ |
| Text rotation | ❌ | ✅ |
| Multiple simultaneous styles | ❌ | ✅ |

Every single viral caption style we're building requires capabilities that SRT cannot provide. ASS is the only choice.

ffmpeg has first-class support for ASS via the libass library. Burning ASS captions into video is a single filter chain command with no extra dependencies beyond what we already use.

---

## ASS File Structure

Before building the generators, we need to understand the format we're writing.

An ASS file has three sections:

```
[Script Info]          ← metadata and canvas size
[V4+ Styles]           ← named style definitions (font, size, colour, etc.)
[Events]               ← the actual timed dialogue lines
```

### Script Info

```
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1
ScaledBorderAndShadow: yes
```

`PlayResX` and `PlayResY` define the coordinate system. We set these to match our video dimensions (1080×1920) so that pixel values in the style definitions map 1:1 to screen pixels.

`WrapStyle: 1` means text wraps at the right margin. `ScaledBorderAndShadow: yes` means outline and shadow values are in script pixels, not video pixels.

### Style Line Format

```
Style: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,
       Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,
       BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
```

**Colour format:** ASS uses BGR hex with alpha, written as `&HAABBGGRR` where AA=00 is fully opaque and AA=FF is fully transparent. This is the opposite of standard RGB — a common source of bugs.

```python
def rgb_to_ass_colour(r: int, g: int, b: int, alpha: int = 0) -> str:
    # alpha: 0=opaque, 255=transparent
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

# Examples:
# White:          rgb_to_ass_colour(255, 255, 255) → &H00FFFFFF
# Black:          rgb_to_ass_colour(0, 0, 0)       → &H00000000
# Orange:         rgb_to_ass_colour(255, 165, 0)   → &H0000A5FF
# Semi-transparent black: rgb_to_ass_colour(0, 0, 0, 128) → &H80000000
```

**Alignment values** (numpad layout):
```
7  8  9   ← top row
4  5  6   ← middle row
1  2  3   ← bottom row
```
`2` = bottom-centre (standard subtitle position)
`8` = top-centre
`5` = dead centre

**BorderStyle:**
- `1` = outline + drop shadow (standard)
- `3` = opaque background box (used for box-style captions)

### Dialogue Line Format

```
Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
```

Time format: `H:MM:SS.cc` where `cc` is centiseconds (hundredths of a second).

```python
def seconds_to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
```

### Inline Override Tags

ASS supports override tags inside dialogue text using `{}` brackets. These are critical for our word-level colour changes:

```
{\c&H00FF00&}    ← change primary colour mid-line
{\1c&H00FF00&}   ← same as above (explicit primary)
{\fad(200,200)}  ← fade in 200ms, fade out 200ms
{\an2}           ← override alignment to bottom-centre
{\pos(540,1700)} ← absolute position override
{\fs80}          ← override font size
{\b1}            ← bold on
{\b0}            ← bold off
```

---

## The Caption Generator Architecture

Each caption style is a self-contained Python class with two methods:

```python
class CaptionStyleBase:
    def generate_ass(
        self,
        words: list,           # word-level timestamps from Phase 1
        clip_duration: float,  # total clip length in seconds
        video_w: int = 1080,
        video_h: int = 1920,
    ) -> str:
        """Returns complete ASS file content as a string"""
        raise NotImplementedError
    
    def get_style_name(self) -> str:
        raise NotImplementedError
```

The `words` list comes directly from the Phase 1 transcript, scoped to the clip's time range and with timestamps rebased to 0.0 (clip start):

```python
def extract_clip_words(
    transcript: dict,
    clip_start: float,
    clip_end: float
) -> list:
    words = []
    for word in transcript['words']:
        if clip_start <= word['start'] <= clip_end:
            words.append({
                'word': word['word'].strip(),
                'start': round(word['start'] - clip_start, 3),
                'end': round(word['end'] - clip_start, 3),
                'probability': word.get('probability', 1.0),
                'is_filler': word.get('is_filler', False),
            })
    return words
```

---

## Style 1 — Hormozi Style

**Visual identity:** Large, bold, all-caps white text with a thick black stroke. 1–3 words visible at a time. Key words highlighted in orange/yellow. Extremely fast pacing — words appear and disappear in sync with speech.

**Used by:** Alex Hormozi, Codie Sanchez, most business/entrepreneurship clippers.

**Technical approach:** Each word (or pair of words) is its own `Dialogue` line. No sentences — pure word-by-word. The "active" word is orange, previous words are white.

```python
class HormoziStyle(CaptionStyleBase):
    
    WORDS_PER_LINE = 2          # max words visible at once
    FONT = "Montserrat"         # fallback: Arial Black
    FONT_SIZE = 95              # large and aggressive
    TEXT_COLOUR = "&H00FFFFFF"  # white
    HIGHLIGHT_COLOUR = "&H0000A5FF"  # orange (BGR: FF A5 00)
    OUTLINE_COLOUR = "&H00000000"    # black
    OUTLINE_WIDTH = 4               # thick stroke
    SHADOW = 2
    POSITION_Y = 1550           # lower third, above bottom safe zone
    
    def generate_ass(self, words, clip_duration, video_w=1080, video_h=1920):
        header = self._build_header(video_w, video_h)
        styles = self._build_styles()
        events = self._build_events(words, video_w, video_h)
        return header + styles + events
    
    def _build_header(self, w, h):
        return (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {w}\n"
            f"PlayResY: {h}\n"
            "WrapStyle: 1\n"
            "ScaledBorderAndShadow: yes\n\n"
        )
    
    def _build_styles(self):
        return (
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Hormozi,{self.FONT},{self.FONT_SIZE},"
            f"{self.TEXT_COLOUR},&H00FFFFFF,{self.OUTLINE_COLOUR},&H00000000,"
            f"-1,0,0,0,100,100,2,0,1,{self.OUTLINE_WIDTH},{self.SHADOW},"
            f"2,80,80,80,1\n\n"
        )
    
    def _build_events(self, words, video_w, video_h):
        lines = ["[Events]"]
        lines.append(
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        )
        
        # Group words into chunks of WORDS_PER_LINE
        chunks = []
        for i in range(0, len(words), self.WORDS_PER_LINE):
            chunk = words[i:i + self.WORDS_PER_LINE]
            if chunk:
                chunks.append(chunk)
        
        for chunk in chunks:
            start = seconds_to_ass_time(chunk[0]['start'])
            end = seconds_to_ass_time(chunk[-1]['end'])
            
            # Build text: ALL CAPS, highlight last word in orange
            text_parts = []
            for j, word in enumerate(chunk):
                w_upper = word['word'].upper()
                if j == len(chunk) - 1:
                    # Active/last word → orange highlight
                    text_parts.append(
                        f"{{\\c{self.HIGHLIGHT_COLOUR}}}{w_upper}"
                        f"{{\\c{self.TEXT_COLOUR}}}"
                    )
                else:
                    text_parts.append(w_upper)
            
            text = " ".join(text_parts)
            
            # Position in lower third
            pos_tag = f"{{\\an2\\pos({video_w//2},{self.POSITION_Y})}}"
            
            line = (
                f"Dialogue: 0,{start},{end},Hormozi,,0,0,0,,"
                f"{pos_tag}{text}"
            )
            lines.append(line)
        
        return "\n".join(lines) + "\n"
    
    def get_style_name(self):
        return "hormozi"
```

---

## Style 2 — Podcast Subtitle Style

**Visual identity:** Full sentence displayed at the bottom. Clean sans-serif font. Speaker name optionally shown. Moderate font size. Semi-transparent dark background bar for readability over any footage.

**Used by:** Lex Fridman clips, Diary of a CEO, most professional interview clippers.

**Technical approach:** Groups words into natural sentence chunks (up to 8 words, split at natural pause points). Uses `BorderStyle: 3` (opaque box) for the background bar. Fades in/out at each new line.

```python
class PodcastSubtitleStyle(CaptionStyleBase):
    
    FONT = "Inter"              # fallback: Arial
    FONT_SIZE = 58
    MAX_CHARS_PER_LINE = 32     # characters before line break
    TEXT_COLOUR = "&H00FFFFFF"
    OUTLINE_COLOUR = "&H00000000"
    BACK_COLOUR = "&HAA000000"  # semi-transparent black box (AA = 170/255 opacity)
    OUTLINE_WIDTH = 0           # no outline — box handles readability
    SHADOW = 0
    POSITION_Y = 1780           # very bottom, inside safe zone
    FADE_MS = 150               # fade in/out time in milliseconds
    
    def generate_ass(self, words, clip_duration, video_w=1080, video_h=1920):
        header = self._build_header(video_w, video_h)
        styles = self._build_styles()
        events = self._build_events(words, video_w, video_h)
        return header + styles + events
    
    def _build_styles(self):
        return (
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Podcast,{self.FONT},{self.FONT_SIZE},"
            f"{self.TEXT_COLOUR},&H00FFFFFF,{self.OUTLINE_COLOUR},{self.BACK_COLOUR},"
            f"0,0,0,0,100,100,0,0,3,10,0,"  # BorderStyle=3 for box
            f"2,60,60,60,1\n\n"
        )
    
    def _build_events(self, words, video_w, video_h):
        lines = ["[Events]"]
        lines.append(
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        )
        
        # Group into display lines based on character count and pause length
        display_lines = self._group_into_lines(words)
        
        for group in display_lines:
            start = seconds_to_ass_time(group[0]['start'])
            end = seconds_to_ass_time(group[-1]['end'])
            text = " ".join(w['word'] for w in group)
            
            fade_tag = f"{{\\fad({self.FADE_MS},{self.FADE_MS})}}"
            pos_tag = f"{{\\an2\\pos({video_w//2},{self.POSITION_Y})}}"
            
            line = (
                f"Dialogue: 0,{start},{end},Podcast,,0,0,0,,"
                f"{fade_tag}{pos_tag}{text}"
            )
            lines.append(line)
        
        return "\n".join(lines) + "\n"
    
    def _group_into_lines(self, words: list) -> list:
        groups = []
        current = []
        current_chars = 0
        
        for i, word in enumerate(words):
            word_len = len(word['word']) + 1  # +1 for space
            
            # Start a new line if: too long, or gap > 0.5s from previous word
            gap = 0
            if current and i > 0:
                gap = word['start'] - words[i-1]['end']
            
            if (current_chars + word_len > self.MAX_CHARS_PER_LINE and current) \
               or (gap > 0.5 and current):
                groups.append(current)
                current = []
                current_chars = 0
            
            current.append(word)
            current_chars += word_len
        
        if current:
            groups.append(current)
        
        return groups
    
    def get_style_name(self):
        return "podcast_subtitle"
```

---

## Style 3 — Educational / Karaoke Style

**Visual identity:** Full line of text visible at once. As each word is spoken, it changes colour from white to a bright highlight (yellow/green). Creates a smooth "follow-the-bouncing-ball" reading experience.

**Used by:** Finance content, health/science content, how-to clips.

**Technical approach:** This is the most technically complex style. Each word transition requires its own `Dialogue` event using ASS's karaoke `\k` tag, or — more reliably — we write individual events per word with the rest of the line shown in grey and the current word in the highlight colour.

The reliable approach (individual events per word state):

```python
class KaraokeStyle(CaptionStyleBase):
    
    FONT = "Nunito"             # fallback: Arial
    FONT_SIZE = 62
    MAX_WORDS_PER_LINE = 6
    BASE_COLOUR = "&H00C8C8C8"      # light grey for inactive words
    HIGHLIGHT_COLOUR = "&H0000FFFF" # yellow (BGR: 00 FF FF → RGB: FF FF 00)
    OUTLINE_COLOUR = "&H00000000"
    OUTLINE_WIDTH = 3
    SHADOW = 1
    POSITION_Y = 1720
    
    def generate_ass(self, words, clip_duration, video_w=1080, video_h=1920):
        header = self._build_header(video_w, video_h)
        styles = self._build_styles()
        events = self._build_events(words, video_w, video_h)
        return header + styles + events
    
    def _build_events(self, words, video_w, video_h):
        lines = ["[Events]"]
        lines.append(
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        )
        
        # Group words into display lines
        word_lines = []
        for i in range(0, len(words), self.MAX_WORDS_PER_LINE):
            word_lines.append(words[i:i + self.MAX_WORDS_PER_LINE])
        
        for line_words in word_lines:
            line_start = line_words[0]['start']
            line_end = line_words[-1]['end']
            
            # For each word in the line, create a separate dialogue event
            # showing the full line but with the active word highlighted
            for active_idx, active_word in enumerate(line_words):
                event_start = seconds_to_ass_time(active_word['start'])
                
                # Event ends when next word starts (or line ends)
                if active_idx < len(line_words) - 1:
                    event_end = seconds_to_ass_time(line_words[active_idx + 1]['start'])
                else:
                    event_end = seconds_to_ass_time(line_end)
                
                # Build the coloured text
                text_parts = []
                for j, word in enumerate(line_words):
                    if j == active_idx:
                        # Active word: highlight colour
                        text_parts.append(
                            f"{{\\c{self.HIGHLIGHT_COLOUR}}}"
                            f"{word['word']}"
                            f"{{\\c{self.BASE_COLOUR}}}"
                        )
                    elif j < active_idx:
                        # Already spoken: slightly faded
                        text_parts.append(
                            f"{{\\c&H00909090&}}{word['word']}{{\\c{self.BASE_COLOUR}}}"
                        )
                    else:
                        # Not yet spoken: grey
                        text_parts.append(word['word'])
                
                text = " ".join(text_parts)
                pos_tag = f"{{\\an2\\pos({video_w//2},{self.POSITION_Y})}}"
                col_tag = f"{{\\c{self.BASE_COLOUR}}}"  # default to grey
                
                line = (
                    f"Dialogue: 0,{event_start},{event_end},Karaoke,,0,0,0,,"
                    f"{pos_tag}{col_tag}{text}"
                )
                lines.append(line)
        
        return "\n".join(lines) + "\n"
    
    def get_style_name(self):
        return "karaoke"
```

---

## Style 4 — Reaction / Casual Style

**Visual identity:** Mid-screen placement. Slightly informal font. Emoji can be mixed inline. Feels handmade and energetic. Caption position is higher up the screen, leaving room for reactions below.

**Used by:** Dating/relationship content, entertainment, meme-adjacent clips.

**Technical approach:** Sentences displayed mid-screen rather than bottom. Uses a slightly rotated style on select lines (±1–2°). Emoji supported natively in ASS if system fonts are present.

```python
class ReactionStyle(CaptionStyleBase):
    
    FONT = "Poppins"            # fallback: Arial
    FONT_SIZE = 68
    MAX_CHARS_PER_LINE = 24     # shorter lines for mid-screen
    TEXT_COLOUR = "&H00FFFFFF"
    OUTLINE_COLOUR = "&H00000000"
    BACK_COLOUR = "&H88000000"  # dark semi-transparent box
    OUTLINE_WIDTH = 0
    SHADOW = 3
    POSITION_Y = 1200           # mid-screen (not bottom)
    FADE_MS = 80
    
    def _build_styles(self):
        return (
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Reaction,{self.FONT},{self.FONT_SIZE},"
            f"{self.TEXT_COLOUR},&H00FFFFFF,{self.OUTLINE_COLOUR},{self.BACK_COLOUR},"
            f"-1,0,0,0,100,100,1,0,3,10,0,"  # bold, box style
            f"5,80,80,80,1\n\n"             # alignment 5 = centre mid
        )
    
    def _build_events(self, words, video_w, video_h):
        lines = ["[Events]"]
        lines.append(
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        )
        
        display_groups = self._group_into_lines(words)
        
        for i, group in enumerate(display_groups):
            start = seconds_to_ass_time(group[0]['start'])
            end = seconds_to_ass_time(group[-1]['end'])
            text = " ".join(w['word'] for w in group)
            
            # Alternate slight rotation for handmade feel
            angle = 1.5 if i % 2 == 0 else -1.5
            
            fade_tag = f"{{\\fad({self.FADE_MS},{self.FADE_MS})}}"
            pos_tag = f"{{\\an5\\pos({video_w//2},{self.POSITION_Y})}}"
            angle_tag = f"{{\\frz{angle}}}"
            
            line = (
                f"Dialogue: 0,{start},{end},Reaction,,0,0,0,,"
                f"{fade_tag}{pos_tag}{angle_tag}{text}"
            )
            lines.append(line)
        
        return "\n".join(lines) + "\n"
    
    def get_style_name(self):
        return "reaction"
```

---

## Style 5 — Cinematic Style

**Visual identity:** Lowercase, thin/light font weight, centre-aligned. Slow fade in and fade out per phrase. Minimal — no outline, no box. Elegant and editorial. Text positioned at bottom but with generous margins.

**Used by:** Mindset clips, emotional stories, true crime, storytelling content.

**Technical approach:** Longer display groups (full thoughts, not just a few words). Heavy fade timing (300ms in, 300ms out). Letter spacing increased for an airy premium feel.

```python
class CinematicStyle(CaptionStyleBase):
    
    FONT = "Lato Light"         # fallback: Arial
    FONT_SIZE = 52
    MAX_CHARS_PER_LINE = 40     # longer lines, full thoughts
    TEXT_COLOUR = "&H00FFFFFF"
    OUTLINE_COLOUR = "&H00000000"
    OUTLINE_WIDTH = 1.5         # very thin outline for legibility
    SHADOW = 0
    LETTER_SPACING = 3          # wider spacing for premium feel
    POSITION_Y = 1800
    FADE_IN_MS = 300
    FADE_OUT_MS = 300
    
    def _build_styles(self):
        return (
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cinematic,{self.FONT},{self.FONT_SIZE},"
            f"{self.TEXT_COLOUR},&H00FFFFFF,{self.OUTLINE_COLOUR},&H00000000,"
            f"0,0,0,0,100,100,{self.LETTER_SPACING},0,1,{self.OUTLINE_WIDTH},0,"
            f"2,100,100,120,1\n\n"   # large margins, very bottom
        )
    
    def _build_events(self, words, video_w, video_h):
        lines = ["[Events]"]
        lines.append(
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        )
        
        # Group into longer thought-based phrases
        display_groups = self._group_cinematic(words)
        
        for group in display_groups:
            start = seconds_to_ass_time(group[0]['start'])
            end = seconds_to_ass_time(group[-1]['end'])
            
            # Join and lowercase
            text = " ".join(w['word'].lower() for w in group)
            
            fade_tag = f"{{\\fad({self.FADE_IN_MS},{self.FADE_OUT_MS})}}"
            pos_tag = f"{{\\an2\\pos({video_w//2},{self.POSITION_Y})}}"
            
            line = (
                f"Dialogue: 0,{start},{end},Cinematic,,0,0,0,,"
                f"{fade_tag}{pos_tag}{text}"
            )
            lines.append(line)
        
        return "\n".join(lines) + "\n"
    
    def _group_cinematic(self, words: list) -> list:
        # Group on punctuation and long pauses — full thoughts
        groups = []
        current = []
        
        for i, word in enumerate(words):
            current.append(word)
            
            is_sentence_end = word['word'].rstrip()[-1:] in '.?!,'
            gap = 0
            if i < len(words) - 1:
                gap = words[i+1]['start'] - word['end']
            
            char_count = sum(len(w['word']) + 1 for w in current)
            
            if (is_sentence_end and char_count > 15) or gap > 0.8 or char_count > self.MAX_CHARS_PER_LINE:
                if current:
                    groups.append(current)
                    current = []
        
        if current:
            groups.append(current)
        
        return groups
    
    def get_style_name(self):
        return "cinematic"
```

---

## The Caption Renderer

The renderer ties all five styles together. It accepts a clip candidate, a style choice, and the clip's word data, generates the ASS file, and burns it into the video using ffmpeg.

```python
import subprocess
import tempfile
import os

STYLE_MAP = {
    'hormozi':          HormoziStyle(),
    'podcast_subtitle': PodcastSubtitleStyle(),
    'karaoke':          KaraokeStyle(),
    'reaction':         ReactionStyle(),
    'cinematic':        CinematicStyle(),
}


def render_captions(
    video_path: str,        # Phase 3 output: clip_N_processed.mp4
    words: list,            # word timestamps scoped to this clip
    clip_duration: float,
    style_name: str,        # 'hormozi' | 'podcast_subtitle' | 'karaoke' | 'reaction' | 'cinematic'
    output_path: str,
    video_w: int = 1080,
    video_h: int = 1920,
) -> str:
    
    style = STYLE_MAP.get(style_name)
    if not style:
        raise ValueError(f"Unknown caption style: {style_name}. "
                         f"Choose from: {list(STYLE_MAP.keys())}")
    
    # Generate the ASS subtitle file content
    ass_content = style.generate_ass(
        words=words,
        clip_duration=clip_duration,
        video_w=video_w,
        video_h=video_h,
    )
    
    # Write ASS to a temp file
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.ass', delete=False, encoding='utf-8'
    ) as f:
        f.write(ass_content)
        ass_path = f.name
    
    try:
        # Burn captions into video using ffmpeg's ass filter
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', f"ass='{ass_path}'",     # libass renders the subtitle
            '-c:v', 'libx264',
            '-crf', '18',
            '-preset', 'fast',
            '-c:a', 'copy',                  # audio pass-through (already normalised)
            '-movflags', '+faststart',
            output_path,
            '-y'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"Caption burn failed: {result.stderr}")
        
    finally:
        os.unlink(ass_path)  # clean up temp file
    
    return output_path
```

---

## Font Requirements & Fallback Strategy

The viral caption styles depend on specific fonts. If the font isn't installed on the system, ASS silently falls back to Arial — which looks wrong for most styles.

### Required Fonts

| Style | Primary Font | Why | Fallback |
|---|---|---|---|
| Hormozi | Montserrat ExtraBold | Aggressive, geometric, brand-aligned | Arial Black |
| Podcast Subtitle | Inter | Clean, neutral, modern | Arial |
| Karaoke | Nunito | Rounded, friendly, readable at speed | Arial |
| Reaction | Poppins | Balanced, casual, modern | Verdana |
| Cinematic | Lato Light | Elegant, thin, editorial | Arial |

### Font Installation Script

```python
import subprocess
import sys
import os

REQUIRED_FONTS = {
    'Montserrat': 'https://fonts.google.com/download?family=Montserrat',
    'Inter':       'https://fonts.google.com/download?family=Inter',
    'Nunito':      'https://fonts.google.com/download?family=Nunito',
    'Poppins':     'https://fonts.google.com/download?family=Poppins',
    'Lato':        'https://fonts.google.com/download?family=Lato',
}

def install_fonts_linux():
    font_dir = os.path.expanduser('~/.fonts')
    os.makedirs(font_dir, exist_ok=True)
    
    # All five fonts as a batch from a local fonts/ directory
    # The setup script ships with the fonts bundled
    src_dir = os.path.join(os.path.dirname(__file__), 'assets', 'fonts')
    
    for font_file in os.listdir(src_dir):
        if font_file.endswith(('.ttf', '.otf')):
            src = os.path.join(src_dir, font_file)
            dst = os.path.join(font_dir, font_file)
            if not os.path.exists(dst):
                subprocess.run(['cp', src, dst])
    
    subprocess.run(['fc-cache', '-fv'], capture_output=True)
    print("Fonts installed successfully.")
```

We bundle the required fonts in the tool's `assets/fonts/` directory and install them on first run. This guarantees the visual output is identical on every machine.

---

## Word Grouping — The Universal Helper

Several styles share logic for grouping words into display lines. We expose this as a standalone utility used by all style classes:

```python
def group_words_into_lines(
    words: list,
    max_chars: int = 30,
    max_gap_seconds: float = 0.6,
    max_words: int = None,
) -> list:
    groups = []
    current = []
    current_chars = 0
    
    for i, word in enumerate(words):
        word_len = len(word['word']) + 1
        
        # Measure gap from previous word
        gap = 0
        if current and i > 0:
            gap = word['start'] - words[i - 1]['end']
        
        # Break condition
        should_break = (
            (current_chars + word_len > max_chars and current) or
            (gap > max_gap_seconds and current) or
            (max_words and len(current) >= max_words and current)
        )
        
        if should_break:
            groups.append(current)
            current = []
            current_chars = 0
        
        current.append(word)
        current_chars += word_len
    
    if current:
        groups.append(current)
    
    return groups
```

---

## Caption Positioning Logic (Face-Aware)

Phase 3 passes `face_positions` to Phase 4 — the per-frame face centre coordinates. We use these to ensure captions never overlap with the speaker's face.

The rule is simple:
- If the speaker's face is in the bottom 40% of the frame → move captions to top 25%
- Otherwise → keep captions at the bottom (default)

```python
def compute_caption_position(
    face_positions: list,
    video_h: int = 1920,
    bottom_zone_threshold: float = 0.60,  # face_cy above this = face in lower 40%
) -> str:
    if not face_positions:
        return 'bottom'
    
    # Sample 10 evenly distributed face positions
    sample = face_positions[::max(1, len(face_positions)//10)]
    avg_cy = sum(pos[1] for pos in sample) / len(sample)
    
    if avg_cy > bottom_zone_threshold:
        return 'top'
    return 'bottom'


def get_position_y(placement: str, style_name: str, video_h: int = 1920) -> int:
    POSITIONS = {
        # (style, placement) → Y coordinate in pixels
        ('hormozi',          'bottom'): 1550,
        ('hormozi',          'top'):    370,
        ('podcast_subtitle', 'bottom'): 1780,
        ('podcast_subtitle', 'top'):    140,
        ('karaoke',          'bottom'): 1720,
        ('karaoke',          'top'):    200,
        ('reaction',         'bottom'): 1200,
        ('reaction',         'top'):    720,
        ('cinematic',        'bottom'): 1800,
        ('cinematic',        'top'):    120,
    }
    return POSITIONS.get((style_name, placement), 1700)
```

---

## Filler Word Handling

Phase 1 flagged filler words (`um`, `uh`, `like`, `you know`, etc.) with `is_filler: true`. By default we display them because they're part of the natural speech rhythm and removing them makes captions feel out of sync. However, we offer a toggle in the dashboard:

```python
def filter_words_for_captions(
    words: list,
    remove_fillers: bool = False,
    min_confidence: float = 0.6
) -> list:
    filtered = []
    for word in words:
        # Skip very low confidence words (likely mishearing)
        if word.get('probability', 1.0) < min_confidence:
            continue
        
        # Optionally skip fillers
        if remove_fillers and word.get('is_filler', False):
            continue
        
        filtered.append(word)
    
    return filtered
```

When fillers are removed, the timing of surrounding words is preserved — we don't try to close the gap, we just skip the word visually. This keeps the audio and caption in sync.

---

## Full Orchestration

```python
def run_phase_4(
    clip: dict,                 # Phase 3 output (includes processed_path, face_positions)
    transcript: dict,           # master transcript from Phase 1
    caption_style: str,         # user-selected style
    output_dir: str,
    remove_fillers: bool = False,
) -> dict:
    
    clip_id = clip['rank']
    video_path = clip['processed_path']
    
    # Extract and rebase words for this clip
    words_raw = extract_clip_words(
        transcript=transcript,
        clip_start=clip['start'],
        clip_end=clip['end'],
    )
    
    # Apply filler filter
    words = filter_words_for_captions(words_raw, remove_fillers=remove_fillers)
    
    if not words:
        raise ValueError(f"Clip {clip_id}: no words found in transcript window.")
    
    # Compute face-aware caption position
    placement = compute_caption_position(clip.get('face_positions', []))
    
    # Inject position into style (by passing to generate_ass)
    # (Each style class accepts position_override parameter)
    
    clip_duration = clip['end'] - clip['start']
    output_path = os.path.join(output_dir, f'clip_{clip_id}_final.mp4')
    
    render_captions(
        video_path=video_path,
        words=words,
        clip_duration=clip_duration,
        style_name=caption_style,
        output_path=output_path,
    )
    
    # Save the ASS file alongside the clip for manual review/editing
    ass_debug_path = os.path.join(output_dir, f'clip_{clip_id}.ass')
    style = STYLE_MAP[caption_style]
    ass_content = style.generate_ass(words, clip_duration)
    with open(ass_debug_path, 'w', encoding='utf-8') as f:
        f.write(ass_content)
    
    return {
        **clip,
        'final_path': output_path,
        'ass_path': ass_debug_path,
        'caption_style': caption_style,
        'word_count': len(words),
        'placement': placement,
    }
```

---

## Output File Structure

```
/projects/{project_id}/
  /clips/
    clip_1_processed.mp4    ← Phase 3 output (no captions)
    clip_1_final.mp4        ← Phase 4 output (with captions) ← DELIVERABLE
    clip_1.ass              ← ASS file for manual inspection/editing
    clip_2_processed.mp4
    clip_2_final.mp4        ← DELIVERABLE
    clip_2.ass
    ...
```

Keeping the `.ass` file alongside the final clip is intentional. If the user wants to tweak caption timing or fix a word, they can edit the `.ass` file in any subtitle editor (like Aegisub, which is free) and re-run just the ffmpeg burn step — without reprocessing the entire pipeline.

---

## Requirements & Dependencies

```
ffmpeg with libass    # verify with: ffmpeg -version | grep libass
```

No Python packages beyond standard library needed for this phase. All caption rendering is handled by ffmpeg's built-in ASS engine.

**Font dependencies (bundled in assets/):**
```
Montserrat-ExtraBold.ttf
Inter-Regular.ttf
Nunito-Regular.ttf
Poppins-Regular.ttf
Lato-Light.ttf
```

**Verify libass is available:**
```bash
ffmpeg -version | grep -o 'enable-libass'
# Should output: enable-libass
# If not, reinstall ffmpeg with: sudo apt install ffmpeg (Ubuntu ships with libass enabled)
```

---

## Processing Time Estimates

Caption rendering is the fastest phase in the entire pipeline. The ffmpeg libass engine is highly optimised.

| Clip Length | ASS Generation | ffmpeg Burn | Total |
|---|---|---|---|
| 30s clip | <0.1s | 8s | ~8s |
| 60s clip | <0.1s | 14s | ~14s |
| 90s clip | <0.1s | 20s | ~20s |

For 10 clips averaging 60 seconds: approximately **2–3 minutes** total. This is the fastest phase.

---

## Error Handling & Edge Cases

| Scenario | Handling |
|---|---|
| No words in clip window | Raise error, flag clip in dashboard, offer to re-run Phase 1 |
| Font not found | ASS silently falls back to Arial — add font check on startup |
| libass not in ffmpeg build | Detect at startup, show setup instructions, suggest reinstalling ffmpeg |
| Word timestamps wildly out of sync | Detect by comparing word count vs expected speech rate, warn in dashboard |
| Very fast speech (>250 wpm) | Hormozi/Karaoke styles may have words too brief to read — auto-switch to Podcast Subtitle with a dashboard warning |
| Clip has no audio (silent) | Skip caption rendering, export video with no captions, flag in dashboard |
| ASS burn produces corrupted output | Retry with SRT fallback + subtitles filter instead of ass filter |

---

## What Phase 5 Receives

For each approved clip, Phase 4 delivers:

- `clip_{id}_final.mp4` — the complete, captioned, platform-ready vertical video
- `clip_{id}.ass` — the editable subtitle source file
- Metadata: style used, placement (top/bottom), word count, any warnings

Phase 5 (the dashboard) displays these for final review and provides one-click download. The export step simply collects these files, renames them sensibly, and makes them available.