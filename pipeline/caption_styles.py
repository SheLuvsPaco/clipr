"""
Caption Styles — Phase 4 style classes.
5 viral caption styles, each generating complete ASS subtitle content.

Styles:
    1. Hormozi    — Bold, all-caps, word-by-word, orange highlight
    2. Podcast    — Clean, sentence chunks, semi-transparent box
    3. Karaoke    — Word-by-word colour sweep, educational
    4. Reaction   — Mid-screen, rotated, casual/energetic
    5. Cinematic  — Lowercase, thin, long fades, editorial
"""

import logging
from pipeline.caption_utils import (
    seconds_to_ass_time,
    group_words_into_lines,
)

logger = logging.getLogger(__name__)


# ─── Base Class ───────────────────────────────────────────────

class CaptionStyleBase:
    """Base class for all caption styles."""

    def generate_ass(
        self,
        words: list,
        clip_duration: float,
        video_w: int = 1080,
        video_h: int = 1920,
    ) -> str:
        """Returns complete ASS file content as a string."""
        raise NotImplementedError

    def get_style_name(self) -> str:
        raise NotImplementedError

    def _build_header(self, w: int, h: int) -> str:
        return (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {w}\n"
            f"PlayResY: {h}\n"
            "WrapStyle: 1\n"
            "ScaledBorderAndShadow: yes\n\n"
        )

    def _build_format_line(self) -> str:
        return (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        )

    def _build_events_header(self) -> list:
        return [
            "[Events]",
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text",
        ]


# ─── Style 1: Hormozi ────────────────────────────────────────

class HormoziStyle(CaptionStyleBase):
    """
    Large bold all-caps white text with thick black stroke.
    1–2 words at a time. Key word highlighted in orange.
    Extremely fast pacing — words sync with speech.
    Used by: Alex Hormozi, Codie Sanchez, business clippers.
    """

    WORDS_PER_LINE     = 2
    FONT               = "Montserrat"
    FONT_SIZE          = 95
    TEXT_COLOUR        = "&H00FFFFFF"      # white
    HIGHLIGHT_COLOUR   = "&H0000A5FF"     # orange (BGR)
    OUTLINE_COLOUR     = "&H00000000"     # black
    OUTLINE_WIDTH      = 4
    SHADOW             = 2
    POSITION_Y         = 1550

    def generate_ass(self, words, clip_duration, video_w=1080, video_h=1920):
        header = self._build_header(video_w, video_h)
        styles = self._build_styles()
        events = self._build_events(words, video_w, video_h)
        return header + styles + events

    def _build_styles(self):
        return (
            "[V4+ Styles]\n"
            f"{self._build_format_line()}\n"
            f"Style: Hormozi,{self.FONT},{self.FONT_SIZE},"
            f"{self.TEXT_COLOUR},&H00FFFFFF,{self.OUTLINE_COLOUR},&H00000000,"
            f"-1,0,0,0,100,100,2,0,1,{self.OUTLINE_WIDTH},{self.SHADOW},"
            f"2,80,80,80,1\n\n"
        )

    def _build_events(self, words, video_w, video_h):
        lines = self._build_events_header()

        # Group words into chunks of WORDS_PER_LINE
        chunks = []
        for i in range(0, len(words), self.WORDS_PER_LINE):
            chunk = words[i:i + self.WORDS_PER_LINE]
            if chunk:
                chunks.append(chunk)

        for chunk in chunks:
            start = seconds_to_ass_time(chunk[0]['start'])
            end   = seconds_to_ass_time(chunk[-1]['end'])

            # Build text: ALL CAPS, highlight last word in orange
            text_parts = []
            for j, word in enumerate(chunk):
                w_upper = word['word'].upper()
                if j == len(chunk) - 1:
                    text_parts.append(
                        f"{{\\c{self.HIGHLIGHT_COLOUR}}}{w_upper}"
                        f"{{\\c{self.TEXT_COLOUR}}}"
                    )
                else:
                    text_parts.append(w_upper)

            text    = " ".join(text_parts)
            pos_tag = f"{{\\an2\\pos({video_w // 2},{self.POSITION_Y})}}"

            lines.append(
                f"Dialogue: 0,{start},{end},Hormozi,,0,0,0,,{pos_tag}{text}"
            )

        return "\n".join(lines) + "\n"

    def get_style_name(self):
        return "hormozi"


# ─── Style 2: Podcast Subtitle ───────────────────────────────

class PodcastSubtitleStyle(CaptionStyleBase):
    """
    Full sentence at the bottom. Clean sans-serif font.
    Semi-transparent dark background bar for readability.
    Fades in/out at each new line.
    Used by: Lex Fridman, Diary of a CEO, professional clippers.
    """

    FONT               = "Inter"
    FONT_SIZE          = 58
    MAX_CHARS_PER_LINE = 32
    TEXT_COLOUR        = "&H00FFFFFF"
    OUTLINE_COLOUR     = "&H00000000"
    BACK_COLOUR        = "&HAA000000"     # semi-transparent black box
    OUTLINE_WIDTH      = 0
    SHADOW             = 0
    POSITION_Y         = 1780
    FADE_MS            = 150

    def generate_ass(self, words, clip_duration, video_w=1080, video_h=1920):
        header = self._build_header(video_w, video_h)
        styles = self._build_styles()
        events = self._build_events(words, video_w, video_h)
        return header + styles + events

    def _build_styles(self):
        return (
            "[V4+ Styles]\n"
            f"{self._build_format_line()}\n"
            f"Style: Podcast,{self.FONT},{self.FONT_SIZE},"
            f"{self.TEXT_COLOUR},&H00FFFFFF,{self.OUTLINE_COLOUR},{self.BACK_COLOUR},"
            f"0,0,0,0,100,100,0,0,3,10,0,"
            f"2,60,60,60,1\n\n"
        )

    def _build_events(self, words, video_w, video_h):
        lines = self._build_events_header()

        display_groups = group_words_into_lines(
            words, max_chars=self.MAX_CHARS_PER_LINE, max_gap_seconds=0.5,
        )

        for group in display_groups:
            start = seconds_to_ass_time(group[0]['start'])
            end   = seconds_to_ass_time(group[-1]['end'])
            text  = " ".join(w['word'] for w in group)

            fade_tag = f"{{\\fad({self.FADE_MS},{self.FADE_MS})}}"
            pos_tag  = f"{{\\an2\\pos({video_w // 2},{self.POSITION_Y})}}"

            lines.append(
                f"Dialogue: 0,{start},{end},Podcast,,0,0,0,,{fade_tag}{pos_tag}{text}"
            )

        return "\n".join(lines) + "\n"

    def get_style_name(self):
        return "podcast_subtitle"


# ─── Style 3: Karaoke / Educational ──────────────────────────

class KaraokeStyle(CaptionStyleBase):
    """
    Full line visible. Active word highlighted in yellow as it's spoken.
    Creates smooth 'follow-the-bouncing-ball' reading experience.
    Each word state = its own Dialogue event for reliability.
    Used by: Finance, health/science, how-to clips.
    """

    FONT               = "Nunito"
    FONT_SIZE          = 62
    MAX_WORDS_PER_LINE = 6
    BASE_COLOUR        = "&H00C8C8C8"     # light grey
    HIGHLIGHT_COLOUR   = "&H0000FFFF"     # yellow (BGR: 00 FF FF)
    SPOKEN_COLOUR      = "&H00909090"     # darker grey for already spoken
    OUTLINE_COLOUR     = "&H00000000"
    OUTLINE_WIDTH      = 3
    SHADOW             = 1
    POSITION_Y         = 1720

    def generate_ass(self, words, clip_duration, video_w=1080, video_h=1920):
        header = self._build_header(video_w, video_h)
        styles = self._build_styles()
        events = self._build_events(words, video_w, video_h)
        return header + styles + events

    def _build_styles(self):
        return (
            "[V4+ Styles]\n"
            f"{self._build_format_line()}\n"
            f"Style: Karaoke,{self.FONT},{self.FONT_SIZE},"
            f"{self.BASE_COLOUR},&H00FFFFFF,{self.OUTLINE_COLOUR},&H00000000,"
            f"0,0,0,0,100,100,0,0,1,{self.OUTLINE_WIDTH},{self.SHADOW},"
            f"2,80,80,80,1\n\n"
        )

    def _build_events(self, words, video_w, video_h):
        lines = self._build_events_header()

        # Group words into display lines
        word_lines = []
        for i in range(0, len(words), self.MAX_WORDS_PER_LINE):
            word_lines.append(words[i:i + self.MAX_WORDS_PER_LINE])

        for line_words in word_lines:
            line_end = line_words[-1]['end']

            # For each word in the line, create a Dialogue event
            # showing the full line with only the active word highlighted
            for active_idx, active_word in enumerate(line_words):
                event_start = seconds_to_ass_time(active_word['start'])

                # Event ends when next word starts (or line ends)
                if active_idx < len(line_words) - 1:
                    event_end = seconds_to_ass_time(
                        line_words[active_idx + 1]['start']
                    )
                else:
                    event_end = seconds_to_ass_time(line_end)

                # Build coloured text: spoken=dark grey, active=yellow, upcoming=grey
                text_parts = []
                for j, word in enumerate(line_words):
                    if j == active_idx:
                        text_parts.append(
                            f"{{\\c{self.HIGHLIGHT_COLOUR}}}"
                            f"{word['word']}"
                            f"{{\\c{self.BASE_COLOUR}}}"
                        )
                    elif j < active_idx:
                        text_parts.append(
                            f"{{\\c{self.SPOKEN_COLOUR}}}"
                            f"{word['word']}"
                            f"{{\\c{self.BASE_COLOUR}}}"
                        )
                    else:
                        text_parts.append(word['word'])

                text    = " ".join(text_parts)
                pos_tag = f"{{\\an2\\pos({video_w // 2},{self.POSITION_Y})}}"
                col_tag = f"{{\\c{self.BASE_COLOUR}}}"

                lines.append(
                    f"Dialogue: 0,{event_start},{event_end},Karaoke,,0,0,0,,"
                    f"{pos_tag}{col_tag}{text}"
                )

        return "\n".join(lines) + "\n"

    def get_style_name(self):
        return "karaoke"


# ─── Style 4: Reaction / Casual ──────────────────────────────

class ReactionStyle(CaptionStyleBase):
    """
    Mid-screen placement. Slightly informal, bold font. Alternating
    slight rotation (±1.5°) for handmade/energetic feel.
    Dark semi-transparent background box.
    Used by: Dating/relationship, entertainment, meme-adjacent clips.
    """

    FONT               = "Poppins"
    FONT_SIZE          = 68
    MAX_CHARS_PER_LINE = 24
    TEXT_COLOUR        = "&H00FFFFFF"
    OUTLINE_COLOUR     = "&H00000000"
    BACK_COLOUR        = "&H88000000"     # dark semi-transparent box
    OUTLINE_WIDTH      = 0
    SHADOW             = 3
    POSITION_Y         = 1200             # mid-screen
    FADE_MS            = 80

    def generate_ass(self, words, clip_duration, video_w=1080, video_h=1920):
        header = self._build_header(video_w, video_h)
        styles = self._build_styles()
        events = self._build_events(words, video_w, video_h)
        return header + styles + events

    def _build_styles(self):
        return (
            "[V4+ Styles]\n"
            f"{self._build_format_line()}\n"
            f"Style: Reaction,{self.FONT},{self.FONT_SIZE},"
            f"{self.TEXT_COLOUR},&H00FFFFFF,{self.OUTLINE_COLOUR},{self.BACK_COLOUR},"
            f"-1,0,0,0,100,100,1,0,3,10,0,"
            f"5,80,80,80,1\n\n"
        )

    def _build_events(self, words, video_w, video_h):
        lines = self._build_events_header()

        display_groups = group_words_into_lines(
            words, max_chars=self.MAX_CHARS_PER_LINE, max_gap_seconds=0.5,
        )

        for i, group in enumerate(display_groups):
            start = seconds_to_ass_time(group[0]['start'])
            end   = seconds_to_ass_time(group[-1]['end'])
            text  = " ".join(w['word'] for w in group)

            # Alternate slight rotation for handmade feel
            angle = 1.5 if i % 2 == 0 else -1.5

            fade_tag  = f"{{\\fad({self.FADE_MS},{self.FADE_MS})}}"
            pos_tag   = f"{{\\an5\\pos({video_w // 2},{self.POSITION_Y})}}"
            angle_tag = f"{{\\frz{angle}}}"

            lines.append(
                f"Dialogue: 0,{start},{end},Reaction,,0,0,0,,"
                f"{fade_tag}{pos_tag}{angle_tag}{text}"
            )

        return "\n".join(lines) + "\n"

    def get_style_name(self):
        return "reaction"


# ─── Style 5: Cinematic ──────────────────────────────────────

class CinematicStyle(CaptionStyleBase):
    """
    Lowercase, thin/light font, centre-aligned. Slow fade per phrase.
    Minimal — no outline, no box. Elegant and editorial.
    Letter spacing increased for airy premium feel.
    Used by: Mindset, emotional stories, true crime, storytelling.
    """

    FONT               = "Lato Light"
    FONT_SIZE          = 52
    MAX_CHARS_PER_LINE = 40
    TEXT_COLOUR        = "&H00FFFFFF"
    OUTLINE_COLOUR     = "&H00000000"
    OUTLINE_WIDTH      = 1.5
    SHADOW             = 0
    LETTER_SPACING     = 3
    POSITION_Y         = 1800
    FADE_IN_MS         = 300
    FADE_OUT_MS        = 300

    def generate_ass(self, words, clip_duration, video_w=1080, video_h=1920):
        header = self._build_header(video_w, video_h)
        styles = self._build_styles()
        events = self._build_events(words, video_w, video_h)
        return header + styles + events

    def _build_styles(self):
        return (
            "[V4+ Styles]\n"
            f"{self._build_format_line()}\n"
            f"Style: Cinematic,{self.FONT},{self.FONT_SIZE},"
            f"{self.TEXT_COLOUR},&H00FFFFFF,{self.OUTLINE_COLOUR},&H00000000,"
            f"0,0,0,0,100,100,{self.LETTER_SPACING},0,1,{self.OUTLINE_WIDTH},0,"
            f"2,100,100,120,1\n\n"
        )

    def _build_events(self, words, video_w, video_h):
        lines = self._build_events_header()

        display_groups = self._group_cinematic(words)

        for group in display_groups:
            start = seconds_to_ass_time(group[0]['start'])
            end   = seconds_to_ass_time(group[-1]['end'])
            text  = " ".join(w['word'].lower() for w in group)

            fade_tag = f"{{\\fad({self.FADE_IN_MS},{self.FADE_OUT_MS})}}"
            pos_tag  = f"{{\\an2\\pos({video_w // 2},{self.POSITION_Y})}}"

            lines.append(
                f"Dialogue: 0,{start},{end},Cinematic,,0,0,0,,"
                f"{fade_tag}{pos_tag}{text}"
            )

        return "\n".join(lines) + "\n"

    def _group_cinematic(self, words: list) -> list:
        """Group on punctuation and long pauses — full thoughts."""
        groups  = []
        current = []

        for i, word in enumerate(words):
            current.append(word)

            # Check for sentence-ending punctuation
            is_sentence_end = word['word'].rstrip()[-1:] in '.?!,'

            # Check gap to next word
            gap = 0
            if i < len(words) - 1:
                gap = words[i + 1]['start'] - word['end']

            char_count = sum(len(w['word']) + 1 for w in current)

            # Break on sentence end (if enough content), long gap, or max chars
            if ((is_sentence_end and char_count > 15)
                    or gap > 0.8
                    or char_count > self.MAX_CHARS_PER_LINE):
                groups.append(current)
                current = []

        if current:
            groups.append(current)

        return groups

    def get_style_name(self):
        return "cinematic"
