# PHASE 2 — AI CLIP SELECTION (GENRE-AWARE)
### The Brain of the Clipping Tool

---

## What This Phase Does

Phase 2 reads the master transcript JSON produced in Phase 1 and identifies the best clip candidates using a genre-aware AI system. It outputs a ranked list of clip candidates — each with timestamps, a quality score, and a human-readable explanation of why it's a strong clip — that the user reviews in the dashboard before anything gets cut.

This phase is entirely AI-driven. No heuristics, no keyword matching, no hardcoded rules. The intelligence lives in the prompts.

---

## The Core Problem This Phase Solves

Most AI clipping tools fail because they treat all content the same. They look for "high energy moments" or "long sentences" or apply a generic virality score. This produces mediocre results because virality is deeply genre-specific.

A clip about how to lose belly fat and a clip about why you should fire your CFO operate on completely different psychological principles. The hook mechanisms are different. The narrative structures are different. The emotional triggers are different. The audience expectation is different.

Our system solves this with genre profiles — deeply informed system prompts that teach the AI what "great" looks like for each specific content category.

---

## Technical Foundation

### Why Groq + Llama 3.3 70B

| Requirement | Why it matters | Groq solution |
|---|---|---|
| Long context | A 2-hour podcast transcript is ~23,000 tokens. We need to fit the whole thing in one call | 128K context window — comfortably fits 5+ hours |
| Speed | Processing 50+ thought blocks per run needs to feel instant | 275 tokens/sec — a full analysis completes in seconds |
| JSON output | We need structured, parseable clip candidates | Native JSON mode supported |
| Free tier | The tool must cost $0 to run | Groq free tier covers our usage volume easily |
| Reasoning quality | Genre-aware scoring requires nuanced judgment | 70B model outperforms smaller models significantly here |

**Model:** `llama-3.3-70b-versatile`
**Context window:** 128,000 tokens
**JSON mode:** Yes (enforced via `response_format`)
**Temperature:** 0.3 — low enough for consistent scoring, enough for creative reasoning

### Token Budget for a 2-Hour Podcast

```
Average speaking rate:          ~150 words/minute
Total words (2 hours):          ~18,000 words
Tokens per word (avg):          ~1.3
Total transcript tokens:        ~23,400 tokens
System prompt + genre profile:  ~2,000 tokens
Output (10 clip candidates):    ~3,000 tokens
─────────────────────────────────────────────
Total per run:                  ~28,400 tokens
Groq free tier daily limit:     ~14,400,000 tokens
Daily runs possible (free):     ~500 runs
```

We are nowhere near hitting limits. The free tier is more than sufficient.

---

## Architecture — Two-Pass System

We use a two-pass approach rather than asking the AI to do everything in one call. This produces significantly better results.

```
PASS 1 — CANDIDATE DISCOVERY
Input:  Full transcript (all thought blocks)
Task:   Find every moment with clip potential
Output: 15–25 rough candidates with timestamps

         ↓

PASS 2 — DEEP SCORING
Input:  Each candidate (expanded context ±30s)
Task:   Score in detail against genre criteria
Output: Top 5–10 scored, ranked, reasoned candidates
```

**Why two passes instead of one?**

In a single pass, the AI has to scan 500+ thought blocks AND apply rigorous scoring criteria simultaneously. This causes it to either miss good moments or apply shallow scoring. Splitting the task gives each pass a clear, achievable goal.

Pass 1 is fast and broad — "find anything promising."
Pass 2 is slow and precise — "score these properly against the genre."

---

## Pass 1 — Candidate Discovery

### What We Send

We send the complete transcript as a flat list of thought blocks, with timestamps and basic metadata:

```python
def build_discovery_prompt(transcript: dict, genre: str) -> str:
    blocks_text = ""
    for block in transcript['thought_blocks']:
        blocks_text += (
            f"[BLOCK {block['id']} | {block['start']:.1f}s–{block['end']:.1f}s "
            f"| {block['end'] - block['start']:.0f}s long"
            f"| filler_ratio: {block.get('filler_ratio', 0):.2f}]\n"
            f"{block['text']}\n\n"
        )
    
    return DISCOVERY_SYSTEM_PROMPT.format(genre=genre) + "\n\n" + blocks_text
```

Each block includes:
- Block ID (for reference in Pass 2)
- Start/end timestamps in seconds
- Duration in seconds
- Filler ratio (how rambling it is)
- The full text of the block

### Discovery System Prompt

```
You are an expert short-form content editor specializing in {genre} content.
Your job is to scan a full podcast transcript and identify every moment 
that has genuine potential as a short-form clip.

Be INCLUSIVE at this stage — you are casting a wide net. It is better 
to include a borderline candidate than to miss a great one. We will 
score these more rigorously in the next step.

A candidate is worth flagging if it contains ANY of the following:
- A strong opening statement that could serve as a hook
- A counterintuitive or surprising claim
- A personal story or vulnerable moment
- A concrete insight or actionable advice
- A memorable analogy or metaphor
- A controversial or debate-worthy opinion
- An emotional peak (anger, excitement, vulnerability, humor)
- A clear problem/solution structure
- A moment that would make someone say "wait, what?" or "I never thought of it that way"

DO NOT flag blocks that:
- Are pure tangents with no resolution
- Reference things outside the clip ("as I mentioned before", "like we discussed")
- Are introductions or outro filler
- Contain mostly filler words (high filler_ratio)
- Are under 25 seconds or over 3 minutes in length
- Require heavy prior context to make sense

Return a JSON array of candidate objects:
{
  "candidates": [
    {
      "block_id": 12,
      "start": 145.3,
      "end": 198.7,
      "hook_preview": "First sentence or two that opens the clip",
      "why_flagged": "One sentence explanation of what makes this promising"
    }
  ]
}

Return candidates only. No preamble. No explanation outside the JSON.
```

### What We Get Back

```json
{
  "candidates": [
    {
      "block_id": 47,
      "start": 1823.4,
      "end": 1891.2,
      "hook_preview": "The reason most businesses fail in their first year has nothing to do with money.",
      "why_flagged": "Strong counterintuitive hook followed by a clear 3-point framework."
    },
    {
      "block_id": 83,
      "start": 3102.8,
      "end": 3167.5,
      "hook_preview": "I got fired from my own company. And it was the best thing that ever happened to me.",
      "why_flagged": "Vulnerable personal story with a redemption arc — strong emotional hook."
    }
  ]
}
```

Typically returns 15–25 candidates from a 2-hour podcast.

---

## Pass 2 — Deep Scoring

For each candidate from Pass 1, we make an individual API call with:
- The candidate text (expanded to include 30 seconds of context before and after)
- The full genre scoring rubric
- A request for a structured score output

We expand context by ±30 seconds to give the AI a complete picture — sometimes a block needs a sentence before it to make sense, and we want the AI to see that.

### Expanding Candidate Context

```python
def expand_candidate_context(
    candidate: dict, 
    transcript: dict, 
    context_seconds: float = 30.0
) -> dict:
    expanded_start = max(0, candidate['start'] - context_seconds)
    expanded_end = min(transcript['duration'], candidate['end'] + context_seconds)
    
    # Collect all words in the expanded window
    context_words = [
        w for w in transcript['words']
        if expanded_start <= w['start'] <= expanded_end
    ]
    
    # Mark which words are in the core clip vs context
    core_words = [
        w for w in context_words
        if candidate['start'] <= w['start'] <= candidate['end']
    ]
    
    return {
        **candidate,
        'context_before': ' '.join(
            w['word'] for w in context_words 
            if w['start'] < candidate['start']
        ),
        'core_text': ' '.join(w['word'] for w in core_words),
        'context_after': ' '.join(
            w['word'] for w in context_words 
            if w['start'] > candidate['end']
        ),
    }
```

### Scoring System Prompt Structure

Each genre has its own scoring prompt. All share the same JSON output schema but the scoring criteria inside are completely different.

**Base structure (shared across all genres):**

```
You are an expert short-form content editor. Score the following clip 
candidate against the {GENRE} scoring criteria below.

CONTEXT BEFORE (not part of the clip):
{context_before}

=== CLIP START ===
{core_text}
=== CLIP END ===

CONTEXT AFTER (not part of the clip):
{context_after}

Clip duration: {duration} seconds

Score this clip on each dimension from 0–10 and return valid JSON only.

{GENRE_SPECIFIC_CRITERIA}

Return:
{
  "hook_score": 0-10,
  "hook_analysis": "What works or doesn't about the opening",
  "narrative_score": 0-10,
  "narrative_analysis": "Does it have a clear arc",
  "standalone_score": 0-10,
  "standalone_analysis": "Can it be understood without context",
  "emotional_score": 0-10,
  "emotional_analysis": "What emotion does it trigger and how strongly",
  "length_score": 0-10,
  "length_analysis": "Is the length appropriate for this genre",
  "total_score": 0-100,
  "verdict": "STRONG" | "DECENT" | "WEAK",
  "suggested_trim_start": seconds_to_trim_from_start_if_any,
  "suggested_trim_end": seconds_to_trim_from_end_if_any,
  "suggested_title": "A punchy title for this clip (used in dashboard)",
  "rejection_reason": "Only fill this if verdict is WEAK — why it fails"
}
```

---

## Genre Profiles

This is where the real intellectual work lives. Each genre profile encodes deep knowledge about what makes content in that space go viral.

---

### Genre 1 — Business & Entrepreneurship

**Target creators:** Jack Neel, Alex Hormozi, Codie Sanchez, MFM Pod, My First Million
**Target platforms:** LinkedIn, TikTok, YouTube Shorts, X
**Ideal clip length:** 45–90 seconds

**What virality looks like in this genre:**
- Counterintuitive business insights ("Everyone tells you to niche down — that's wrong")
- Specific numbers and concrete claims ("I went from $0 to $3M in 18 months by doing one thing")
- Frameworks with names ("The 3-lever business model", "The ROAS trap")
- Strong opinions stated as facts with confidence
- Calling out common mistakes ("Stop doing X if you want Y")

**Scoring criteria injected into prompt:**

```
BUSINESS & ENTREPRENEURSHIP SCORING CRITERIA:

HOOK (0-10):
- 10: Opens with a bold counterintuitive claim, specific number, or 
      "everyone is wrong about X" framing. No warm-up required.
- 7-9: Clear, direct opening that establishes a strong point of view.
- 4-6: Decent opening but starts with context or setup instead of 
       jumping into the insight.
- 0-3: Starts with "so", "um", "yeah", or requires the listener to 
       already know who/what is being discussed.

NARRATIVE (0-10):
- 10: Follows Problem → Insight → Evidence → Application. Has a clear 
      payoff. The last sentence lands with force.
- 7-9: Has most of these elements. One is slightly weak.
- 4-6: The insight is there but the structure is loose or it trails off.
- 0-3: Rambling, no clear point, or ends mid-thought.

STANDALONE (0-10):
- 10: A viewer with no knowledge of the podcast or creator understands 
      and gains value immediately.
- 7-9: Mostly self-contained. Minor reference to context that doesn't 
       confuse.
- 4-6: Requires some prior context but the core message still lands.
- 0-3: Says things like "as I said earlier", "what we talked about", 
       references unnamed "they" throughout.

EMOTIONAL (0-10):
- 10: Triggers aspiration, provocation, or "I need to share this" 
      response. Makes the viewer feel smart or challenged.
- 7-9: Clear emotional pull — inspiring, thought-provoking, or validates 
       something the viewer believes.
- 4-6: Interesting but doesn't trigger a strong response.
- 0-3: Flat, informational without resonance.

LENGTH (0-10):
- 10: 45–75 seconds. Long enough to deliver the full insight, short 
      enough to hold attention.
- 7: 75–90 seconds. Slightly long but justified.
- 4: 90–120 seconds. Starts feeling too long.
- 0-3: Under 25 seconds (incomplete) or over 2 minutes (loses attention).

AUTOMATIC DISQUALIFIERS (set total_score to 0):
- Contains earnings claims or specific financial advice
- Starts or ends mid-sentence
- References visual content ("look at this chart", "as you can see here")
- Promotes a specific product/service in a way that feels like an ad
```

---

### Genre 2 — Self-Improvement & Mindset

**Target creators:** Jay Shetty, Mel Robbins, Impact Theory, Andrew Huberman
**Target platforms:** Instagram Reels, TikTok, YouTube Shorts
**Ideal clip length:** 30–75 seconds

**What virality looks like in this genre:**
- Personal transformation stories with a before/after arc
- A relatable struggle immediately named ("If you've ever felt like you're not enough...")
- Actionable micro-advice with specificity ("Do this for 5 minutes every morning")
- Reframes of common experiences ("What you call procrastination is actually your brain protecting you")

**Scoring criteria injected into prompt:**

```
SELF-IMPROVEMENT & MINDSET SCORING CRITERIA:

HOOK (0-10):
- 10: Opens with a relatable universal struggle OR a surprising reframe 
      of something the viewer has experienced. Feels like the speaker 
      is talking directly to them.
- 7-9: Clear, emotionally resonant opening that identifies an audience pain point.
- 4-6: Good insight but opens too abstractly or philosophically.
- 0-3: Generic motivational language ("you've got this", "believe in yourself") 
       with no specificity.

NARRATIVE (0-10):
- 10: Follows Struggle → Realization → Shift → New Way of Being. 
      Ends with a clear, memorable takeaway the viewer can use today.
- 7-9: Strong arc, slightly weak on one dimension.
- 4-6: The insight is valuable but the personal element or takeaway is missing.
- 0-3: Vague inspiration without a clear lesson or change.

STANDALONE (0-10):
- 10: Someone who has never heard of this creator gets immediate value 
      and feels understood.
- 7-9: Mostly self-contained. Context doesn't confuse.
- 0-6: Requires knowing the story from earlier in the episode.

EMOTIONAL (0-10):
- 10: Makes the viewer feel seen, hopeful, or motivated to change something. 
      Save-worthy content.
- 7-9: Clearly resonates emotionally. Share-worthy.
- 4-6: Nice sentiment but doesn't land with force.
- 0-3: Motivational fluff without genuine emotional depth.

LENGTH (0-10):
- 10: 30–60 seconds. This genre moves fast.
- 7: 60–75 seconds.
- 4: 75–90 seconds.
- 0-3: Under 20 seconds or over 2 minutes.

AUTOMATIC DISQUALIFIERS:
- Clip is just general affirmations ("you are enough", "keep going") with no insight
- Ends without a clear takeaway
- Requires knowing who the speaker is to appreciate the story
```

---

### Genre 3 — Finance & Investing

**Target creators:** Graham Stephan, Andrei Jikh, George Kamel, We Study Billionaires
**Target platforms:** YouTube Shorts, TikTok, X
**Ideal clip length:** 45–90 seconds

**What virality looks like in this genre:**
- A specific number that surprises ("If you invested $1,000 in Apple in 2010...")
- Debunking a common financial belief ("Your financial advisor is making more money than you")
- A clear prediction or take on where things are going
- A simple framework that makes complex finance feel accessible

**Scoring criteria injected into prompt:**

```
FINANCE & INVESTING SCORING CRITERIA:

HOOK (0-10):
- 10: Opens with a specific, surprising statistic or a "most people get 
      this wrong" framing about money. Concrete is better than abstract.
- 7-9: Clear financial insight stated directly with confidence.
- 4-6: Good information but opens with setup instead of jumping to the point.
- 0-3: Opens with generic financial advice ("save more than you spend").

NARRATIVE (0-10):
- 10: Follows Context (the problem/current state) → Claim (the insight) 
      → Evidence (why it's true) → Application (what to do). 
      The evidence must be present — not just an assertion.
- 7-9: Has most elements. Evidence slightly thin.
- 4-6: Good claim but no evidence or no application.
- 0-3: Just an opinion with no structure.

STANDALONE (0-10):
- 10: Someone who knows nothing about investing understands this clip 
      AND walks away knowing something actionable.
- 7-9: Mostly accessible. Minor jargon that doesn't confuse.
- 4-6: Contains unexplained jargon or assumes knowledge.
- 0-3: Only makes sense to someone already following this topic closely.

EMOTIONAL (0-10):
- 10: Triggers the "oh shit I need to change something" feeling, 
      or genuine curiosity to learn more. Makes finance feel urgent.
- 7-9: Interesting and credible. Share-worthy.
- 4-6: Informative but doesn't create urgency.
- 0-3: Dry or overly technical.

LENGTH (0-10):
- 10: 45–75 seconds. Enough time to present evidence.
- 7: 75–90 seconds.
- 4: 90–120 seconds.
- 0-3: Under 30 seconds (no room for evidence) or over 2 minutes.

AUTOMATIC DISQUALIFIERS:
- Specific buy/sell recommendations ("buy X stock right now")
- Uses phrases like "not financial advice" prominently (kills engagement)
- References a chart or visual the viewer can't see
- Contains complex terminology that needs a 30-second explainer
```

---

### Genre 4 — Health & Fitness

**Target creators:** Andrew Huberman, Dr. Rhonda Patrick, Thomas DeLauer
**Target platforms:** Instagram Reels, YouTube Shorts, TikTok
**Ideal clip length:** 30–60 seconds

**What virality looks like in this genre:**
- Myth busting ("The reason you're not losing weight has nothing to do with calories")
- A surprising science fact stated simply ("Cold exposure for 11 minutes per week...")
- Clear before/after or cause/effect framing
- Protocol-based advice with specificity (time, duration, frequency)

**Scoring criteria injected into prompt:**

```
HEALTH & FITNESS SCORING CRITERIA:

HOOK (0-10):
- 10: Opens by challenging a common belief OR with a specific scientific 
      claim that surprises. "Most people think X. The science says Y."
- 7-9: Clear and direct health/fitness insight with authority.
- 4-6: Good info but generic opening ("exercise is important for health").
- 0-3: Opens with credentials, disclaimers, or overly cautious language.

NARRATIVE (0-10):
- 10: Common Belief → Why It's Wrong (or incomplete) → The Real Mechanism 
      → What To Do Instead. Ends with a specific, actionable protocol.
- 7-9: Good structure. Protocol slightly vague.
- 4-6: Insight present but no protocol.
- 0-3: Vague or contradicts established health consensus without evidence.

STANDALONE (0-10):
- 10: A general audience viewer immediately understands and can act on this.
- 7-9: Mostly clear. Minor technical term that doesn't confuse.
- 4-6: Assumes background knowledge.
- 0-3: Full of jargon or references a previous explanation.

EMOTIONAL (0-10):
- 10: Creates either "I'm doing this wrong" urgency or "I can actually 
      do this" hope. Saves well.
- 7-9: Interesting. Clearly useful.
- 4-6: Good info but doesn't create action urge.
- 0-3: Sounds like a textbook.

LENGTH (0-10):
- 10: 30–55 seconds. This genre respects the viewer's time.
- 7: 55–70 seconds.
- 4: 70–90 seconds.
- 0-3: Under 20 seconds or over 90 seconds.

AUTOMATIC DISQUALIFIERS:
- Contains specific dosage recommendations for supplements or medications
- Makes medical claims that could harm viewers if followed incorrectly
- References equipment the viewer needs to see ("like this machine here")
- Contradicts basic established medical science without qualification
```

---

### Genre 5 — Relationships & Dating

**Target creators:** Matthew Hussey, Alex Hormozi (relationship content), 
                    We're Not Really Strangers podcast
**Target platforms:** TikTok, Instagram Reels
**Ideal clip length:** 30–60 seconds

**What virality looks like in this genre:**
- A relatable scenario immediately named ("You know that feeling when someone goes cold on you...")
- A hot take that validates something people already feel but never said out loud
- A reframe of a painful experience as something understandable
- Concrete advice stated with warmth and authority

**Scoring criteria injected into prompt:**

```
RELATIONSHIPS & DATING SCORING CRITERIA:

HOOK (0-10):
- 10: Opens with a specific relatable scenario OR a hot take that 
      immediately divides the audience (agree/disagree strongly). 
      Should make the viewer stop scrolling.
- 7-9: Emotionally resonant opening that identifies a universal experience.
- 4-6: Decent but opens too generally ("relationships are hard").
- 0-3: Clinical, preachy, or opens with a disclaimer.

NARRATIVE (0-10):
- 10: Follows Scenario → Why It Happens (with empathy) → What It Means 
      → How To Think About It Differently. 
      Ends on insight or warm challenge, not a lecture.
- 7-9: Good arc. Slightly lacking in one dimension.
- 4-6: Good insight but too preachy or abstract.
- 0-3: Lectures the audience without empathy. Feels judgmental.

STANDALONE (0-10):
- 10: Complete strangers understand and feel understood by this clip.
- 7-9: Self-contained with minor context dependency.
- 4-6: Requires knowing who the host or guest is.
- 0-3: Deeply contextual to a specific situation in the episode.

EMOTIONAL (0-10):
- 10: Makes the viewer feel seen, validated, or gently challenged. 
      Comment-worthy. People will tag a friend.
- 7-9: Clearly emotionally resonant.
- 4-6: Interesting but doesn't hit emotionally.
- 0-3: Cold, clinical, or preachy.

LENGTH (0-10):
- 10: 30–55 seconds. Emotional content needs to move fast.
- 7: 55–70 seconds.
- 4: 70–90 seconds.
- 0-3: Under 20 seconds or over 90 seconds.

AUTOMATIC DISQUALIFIERS:
- Gives advice that could harm someone in a dangerous relationship
- Contains gender stereotypes stated as universal facts
- Is culturally specific to a degree that alienates most viewers
- Ends on ambiguity — no clear insight or takeaway
```

---

### Genre 6 — True Crime & Storytelling

**Target creators:** Crime Junkie, My Favorite Murder, Court Junkie
**Target platforms:** TikTok, Instagram Reels, YouTube Shorts
**Ideal clip length:** 60–90 seconds

**What virality looks like in this genre:**
- Dropping into the middle of a tense moment
- A shocking fact or twist revealed mid-clip
- An open loop that makes the viewer want the full episode
- Vivid, specific details that create atmosphere

**Scoring criteria injected into prompt:**

```
TRUE CRIME & STORYTELLING SCORING CRITERIA:

HOOK (0-10):
- 10: Drops directly into action or tension. No setup. 
      "She opened the door and knew immediately something was wrong."
      Creates an open loop in the first 5 seconds.
- 7-9: Strong tension or intrigue established quickly.
- 4-6: Sets up tension but takes too long to get there.
- 0-3: Opens with case background, dates, or administrative details.

NARRATIVE (0-10):
- 10: Has a mini arc within the clip — tension builds toward a partial 
      revelation or twist. Ends at a high point that makes viewers want 
      more. Does NOT resolve fully (leaves an open loop).
- 7-9: Good arc, partial open loop.
- 4-6: Has tension but no satisfying mini-arc within the clip.
- 0-3: Just information delivery with no narrative shape.

STANDALONE (0-10):
- 10: Someone who doesn't know the case feels the tension and wants 
      to know more.
- 7-9: Mostly accessible. Minor context needed.
- 4-6: Requires knowing the case already.
- 0-3: Only makes sense if you've heard the full episode.

EMOTIONAL (0-10):
- 10: Creates genuine suspense, horror, or empathy. Hard to scroll past.
- 7-9: Clearly tension-inducing or emotionally compelling.
- 4-6: Interesting but doesn't create strong emotional response.
- 0-3: Flat information delivery.

LENGTH (0-10):
- 10: 60–90 seconds. Storytelling needs time to build.
- 7: 90–120 seconds.
- 4: 45–60 seconds (slightly too short for a full mini-arc).
- 0-3: Under 30 seconds or over 2 minutes.

AUTOMATIC DISQUALIFIERS:
- Includes graphic descriptions of violence against specific real victims 
  in a way that feels exploitative
- Speculates about guilt of real people not convicted
- Reveals the full resolution (no reason to watch the full episode)
- References images or maps the viewer can't see
```

---

## The Scoring & Ranking Engine

After all Pass 2 calls complete, we compute a final ranking.

### Score Calculation

```python
SCORE_WEIGHTS = {
    'hook_score':       0.30,   # Most important — you either stop the scroll or you don't
    'narrative_score':  0.25,   # Second most important — does it land
    'standalone_score': 0.20,   # Must make sense without context
    'emotional_score':  0.15,   # Emotional pull drives shares/saves
    'length_score':     0.10,   # Tiebreaker
}

def compute_final_score(scores: dict) -> float:
    weighted = sum(
        scores[key] * weight 
        for key, weight in SCORE_WEIGHTS.items()
    )
    return round(weighted * 10, 1)  # Returns 0–100
```

### Diversity Filter

After ranking, we apply a diversity filter to prevent 5 clips from the same 10-minute section of the podcast:

```python
def apply_diversity_filter(
    candidates: list, 
    min_gap_seconds: float = 300.0,  # 5 minutes
    max_results: int = 10
) -> list:
    selected = []
    for candidate in sorted(candidates, key=lambda x: x['final_score'], reverse=True):
        # Check if this candidate is too close to any already selected
        too_close = any(
            abs(candidate['start'] - s['start']) < min_gap_seconds
            for s in selected
        )
        if not too_close:
            selected.append(candidate)
        if len(selected) >= max_results:
            break
    return selected
```

This ensures the output covers the full podcast, not just the best 10-minute stretch.

---

## Full Implementation

```python
from groq import Groq
import json
import asyncio

client = Groq()  # reads GROQ_API_KEY from env

async def run_phase_2(
    transcript: dict,
    genre: str,
    max_clips: int = 10
) -> list:
    
    # PASS 1 — Discovery
    discovery_prompt = build_discovery_prompt(transcript, genre)
    
    discovery_response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "user", "content": discovery_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=4000,
    )
    
    candidates = json.loads(
        discovery_response.choices[0].message.content
    )['candidates']
    
    print(f"Pass 1 found {len(candidates)} candidates")
    
    # PASS 2 — Deep Scoring (parallel calls for speed)
    genre_criteria = GENRE_PROFILES[genre]['scoring_criteria']
    
    scoring_tasks = [
        score_candidate(candidate, transcript, genre_criteria)
        for candidate in candidates
    ]
    
    scored_candidates = await asyncio.gather(*scoring_tasks)
    
    # Filter out WEAK verdicts
    valid = [c for c in scored_candidates if c['verdict'] != 'WEAK']
    
    # Compute weighted final scores
    for candidate in valid:
        candidate['final_score'] = compute_final_score(candidate)
    
    # Apply diversity filter and return top results
    final_clips = apply_diversity_filter(valid, max_results=max_clips)
    
    print(f"Phase 2 complete. Returning {len(final_clips)} clip candidates.")
    return final_clips


async def score_candidate(
    candidate: dict, 
    transcript: dict, 
    genre_criteria: str
) -> dict:
    expanded = expand_candidate_context(candidate, transcript)
    
    scoring_prompt = build_scoring_prompt(expanded, genre_criteria)
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "user", "content": scoring_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=1000,
    )
    
    scores = json.loads(response.choices[0].message.content)
    return {**candidate, **scores}
```

---

## Phase 2 Output Schema

The final output is a list of clip candidates ready for the review dashboard:

```json
[
  {
    "rank": 1,
    "block_id": 47,
    "start": 1823.4,
    "end": 1891.2,
    "duration": 67.8,
    "suggested_title": "The Real Reason 90% of Businesses Fail",
    "hook_preview": "The reason most businesses fail in their first year has nothing to do with money.",
    "hook_score": 9,
    "hook_analysis": "Strong counterintuitive opener. Immediately challenges a common assumption.",
    "narrative_score": 8,
    "narrative_analysis": "Clear problem → insight → 3-part framework. Ends with a strong call to action.",
    "standalone_score": 10,
    "standalone_analysis": "Zero dependency on outside context. Works cold.",
    "emotional_score": 8,
    "emotional_analysis": "Provokes urgency and the 'I need to fix this' response.",
    "length_score": 9,
    "length_analysis": "67 seconds is ideal for business content. Right in the sweet spot.",
    "final_score": 88.5,
    "verdict": "STRONG",
    "suggested_trim_start": 0,
    "suggested_trim_end": 3.2,
    "genre": "business"
  }
]
```

---

## Error Handling & Edge Cases

| Scenario | Handling |
|---|---|
| Pass 1 returns fewer than 5 candidates | Lower threshold and re-run with more permissive prompt |
| Pass 2 returns all WEAK scores | Flag to user — transcript may be low quality or wrong genre selected |
| Groq rate limit hit | Exponential backoff, retry after 5 seconds |
| JSON parsing fails | Retry call once with stricter JSON instruction, then skip candidate |
| Candidate blocks are too similar | Diversity filter handles this |
| Very short podcast (<30 min) | Skip Pass 1, run all blocks through Pass 2 directly |

---

## Prompt Refinement Loop (How It Gets Smarter Over Time)

The most important long-term feature. Every time the user approves or rejects a clip candidate in the dashboard, that decision gets logged:

```json
{
  "timestamp": "2026-02-21T18:33:00Z",
  "candidate_score": 78.5,
  "user_decision": "rejected",
  "rejection_reason": "Too long, trails off at the end",
  "genre": "business",
  "clip_duration": 112.4
}
```

Over time, patterns emerge. If users consistently reject clips over 90 seconds in the business genre, the length scoring weights update. If clips with hook_score < 7 are always rejected, we raise the minimum threshold.

This is built in Phase 5 (Dashboard) but the data structure is established here.

---

## Requirements & Dependencies

```
groq>=0.12.0         # Groq Python SDK
python-dotenv        # For GROQ_API_KEY env var
asyncio              # Built-in — parallel scoring calls
```

No additional system dependencies. Phase 2 is pure Python + API calls.

**Environment:**
```bash
GROQ_API_KEY=your_key_here
```

---

## Processing Time Estimates

| Podcast Length | Pass 1 | Pass 2 (avg 20 candidates) | Total |
|---|---|---|---|
| 30 minutes | ~3 seconds | ~20 seconds | ~25 seconds |
| 1 hour | ~5 seconds | ~30 seconds | ~35 seconds |
| 2 hours | ~8 seconds | ~45 seconds | ~55 seconds |
| 3 hours | ~12 seconds | ~60 seconds | ~75 seconds |

Phase 2 is by far the fastest phase. The heavy lifting is Phase 1 (transcription). Phase 2 is almost instant by comparison.

---

## What Phase 3 Receives

A ranked, scored, diversity-filtered list of clip candidates, each containing:

- Exact start/end timestamps in seconds
- A suggested title for the dashboard
- Scores and analysis for each dimension
- A trim suggestion if the AI detected dead air at the start or end
- The genre it was scored against

Phase 3 uses these timestamps to cut the actual clips from the original video file.