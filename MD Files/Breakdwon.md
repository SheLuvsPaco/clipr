# PROJECT BRIEFING
## AI-Powered Short-Form Content Clipping Tool

---

## What We Are Building

A local web application that takes long-form video content — primarily podcasts of 1-3 hours — and automatically finds, cuts, captions, and exports short-form clips ready to post on TikTok, Instagram Reels, and YouTube Shorts.

The tool runs entirely on your own machine. No subscriptions, no per-clip fees, no third-party cloud processing. You upload a video or paste a URL, configure your settings, and the system handles everything from transcription to final captioned clip.

The end goal is a one-person operation that can process a full podcast episode and produce 5-10 platform-ready clips in under an hour, with minimal manual effort.

---

## The Problem We're Solving

The content clipping market is exploding. Platforms like ContentRewards.com pay creators $1.50–$2.00 per 1,000 views on clips they post, and long-form creators actively pay clippers to distribute their content. The opportunity is real and growing.

The bottleneck is production speed. Doing this manually means:
- Watching hours of content to find good moments
- Hand-cutting clips in CapCut or Premiere
- Manually adding captions
- Repeating this for every clip, every video, every creator

Most clippers can produce 2-3 clips per hour manually. Our tool targets 5-10 clips per run with a review-and-approve workflow — meaning the human stays in control of quality but the machine does all the grunt work.

The secondary use case is agencies and educators who want to clip multiple creators at scale, or teach students this workflow as a marketable skill.

---

## Who This Is For

**Primary user:** A solo clipper working with ContentRewards-style campaigns, clipping podcasts and long-form content for multiple creators, posting on TikTok, Instagram, and YouTube Shorts.

**Secondary users:**
- Agencies running clipping operations for multiple clients
- Educators teaching content automation
- Creators who want to repurpose their own long-form content

**Technical level assumed:** The user is comfortable with Python and running local tools. This is not a no-code SaaS — it's a self-hosted tool with a clean UI layer on top.

---

## How It Works — The Full Flow

```
[User opens dashboard]
         ↓
[Pastes YouTube URL or uploads video file]
         ↓
[Selects genre: Business / Fitness / Finance / etc.]
         ↓
[Selects caption style: Hormozi / Podcast / Cinematic / etc.]
         ↓
[Hits "Process"]
         ↓
─────────────────────────────────────
PHASE 1 — INGESTION & TRANSCRIPTION
─────────────────────────────────────
• Downloads video (yt-dlp)
• Extracts and preprocesses audio (ffmpeg)
• Transcribes full video with word-level timestamps (faster-whisper)
• Segments transcript into thought blocks
• Saves master transcript JSON
         ↓
─────────────────────────────────────
PHASE 2 — AI CLIP SELECTION
─────────────────────────────────────
• Loads transcript + genre profile
• Genre-specific AI prompt evaluates each thought block
• Scores candidates on hook strength, narrative, clarity
• Returns top 5-10 clip candidates with reasoning
         ↓
─────────────────────────────────────
PHASE 3 — CLIP GENERATION
─────────────────────────────────────
• User reviews candidates in dashboard (approve / reject / trim)
• Approved clips are cut from original video (ffmpeg)
• Vertical crop + reframe applied (9:16 format)
• Basic color grade applied
         ↓
─────────────────────────────────────
PHASE 4 — CAPTION RENDERING
─────────────────────────────────────
• Word-level timestamps used to sync captions
• Selected caption style applied (Hormozi / Podcast / Cinematic / etc.)
• Captions burned into video
         ↓
─────────────────────────────────────
PHASE 5 — EXPORT
─────────────────────────────────────
• Final clips exported as MP4
• Named and organized by creator/episode
• Ready to upload to TikTok, IG Reels, YouTube Shorts
```

---

## The Genre System

This is the core differentiator of the tool. Most clipping tools treat all content the same. We don't.

Each genre has a completely different definition of what makes a great clip. A viral business clip operates on completely different rules than a viral fitness clip or a true crime clip. The AI needs to understand this.

**Genres we're building for (Phase 2+):**

| Genre | Hook Style | Narrative Style | Clip Length |
|---|---|---|---|
| Business / Entrepreneurship | Counterintuitive claim, contrarian take | Problem → Insight → Application | 45–90s |
| Self-Improvement / Mindset | Personal revelation, bold statement | Struggle → Realization → Shift | 30–75s |
| Finance / Investing | Shocking stat, future prediction | Context → Claim → Evidence | 45–90s |
| Health / Fitness | Before/after framing, myth-busting | Common belief → Why it's wrong → Fix | 30–60s |
| Relationships / Dating | Relatable scenario, hot take | Setup → Twist → Takeaway | 30–60s |
| True Crime / Storytelling | Tension-first, open loop | Hook → Build tension → Partial payoff | 60–90s |

Each genre gets its own system prompt in Phase 2, its own scoring criteria, and its own clip length targets.

---

## Caption Styles

Captions are not optional decoration — they are one of the primary reasons clips perform. Studies consistently show 85%+ of social media video is watched on mute. The caption style also establishes the visual identity of the channel.

**Five styles we're shipping:**

**1. Hormozi Style**
Large, bold, all-caps white text with black stroke. 1-3 words per frame. Extremely fast paced. Key words highlighted in orange or yellow. Popularized by Alex Hormozi and now standard in the business/entrepreneurship space.

**2. Podcast Subtitle Style**
Full sentence displayed at bottom of screen. Clean sans-serif font. Speaker name optionally shown. More readable, less aggressive. Works for interview content where you want a professional feel.

**3. Reaction / Casual Style**
Mid-screen placement. Emoji integrated inline with text. Slightly rotated font. Feels handmade and lo-fi. Works for entertainment, dating, and lifestyle content.

**4. Educational / Karaoke Style**
Word-by-word highlighting as each word is spoken. Color shifts from white to yellow as the word is said. Clean background bar behind text. Optimal for finance, health, and how-to content where comprehension matters.

**5. Cinematic Style**
Lowercase thin font, center-aligned. Slow fade in and out per line. Minimal, editorial feel. Used for emotional stories, mindset content, and true crime.

Each style is a preset — the user picks one before rendering. No manual styling required.

---

## What We Are NOT Building

Being explicit about scope prevents scope creep.

- **Not a SaaS.** No user accounts, no cloud hosting, no payments. This runs locally.
- **Not an auto-poster.** The tool exports clips. Posting is manual or handled separately. Platforms are hostile to auto-posting from new accounts and the review step is intentional.
- **Not a video editor.** We're not building a timeline, effects library, or creative suite. The tool does one job: find great clips, cut them, caption them.
- **Not multilingual (v1).** English-only for the first version. Whisper supports many languages and we can extend later.
- **Not a speaker diarization tool (v1).** We're not labeling who says what in the transcript. The AI infers this from context. Diarization can be added in v2.

---

## Tech Stack

| Layer | Tool | Why |
|---|---|---|
| Frontend (Dashboard) | React | Fast to build, component-based |
| Backend | FastAPI (Python) | All processing is Python, keep it native |
| Video Download | yt-dlp | Industry standard, 1700+ sites |
| Audio Processing | ffmpeg | Free, universal, battle-tested |
| Transcription | faster-whisper | 4x faster than vanilla Whisper, CPU-friendly |
| AI Clip Selection | Groq API (llama-3.3-70b) | Free tier, extremely fast inference |
| Video Cutting & Rendering | ffmpeg + moviepy | Free, no rendering fees |
| Caption Rendering | ffmpeg ASS subtitles | Full style control, burned into video |

**Total running cost: $0** assuming Groq free tier usage.

---

## Project Phases

| Phase | What Gets Built | Status |
|---|---|---|
| Phase 1 | Ingestion & Transcription | Planned — fully documented |
| Phase 2 | AI Clip Selection (Genre-Aware) | Planned |
| Phase 3 | Clip Cutting & Video Processing | Planned |
| Phase 4 | Caption Rendering (All Styles) | Planned |
| Phase 5 | Dashboard UI | Planned |
| Phase 6 | Export & File Management | Planned |

Each phase is fully documented before code is written. Code is only written after the plan is locked.

---

## Key Design Principles

**1. Human stays in the loop.**
The AI suggests. The human approves. Every clip goes through a review step before rendering. This keeps quality high and prevents garbage output at scale.

**2. Genre specificity over generalism.**
A tool that works excellently for business podcasts and fitness content is more valuable than one that works mediocrely for everything. We build genre profiles properly.

**3. The transcript is the foundation.**
Everything downstream — clip selection, caption sync, quality scoring — depends on the transcript being accurate and properly structured. Phase 1 gets the most engineering attention.

**4. No internet required after setup.**
Once the tool is installed and models are downloaded, it runs fully offline. This matters for privacy, speed, and reliability.

**5. Speed over perfection on first pass.**
The tool produces 80% quality automatically. The human review step handles the remaining 20%. We don't over-engineer the automation — we make the review step frictionless.

---

## Success Metrics

The tool is working correctly when:

- A 2-hour podcast is fully transcribed in under 25 minutes on a standard laptop
- The AI correctly identifies at least 3 genuinely strong clip candidates per hour of content
- All 5 caption styles render correctly and sync to speech within 100ms
- A complete run from URL to exported clips takes under 60 minutes total
- Clips require minimal manual trimming after AI selection

---

## Current Status

Planning and architecture phase. Phase 1 is fully documented. Building begins after all phases are planned.

**Immediate next step:** Complete Phase 2 documentation (AI Clip Selection).