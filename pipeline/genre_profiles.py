"""
Genre Profiles — Deep scoring criteria for each content genre.
Each genre has its own definition of what makes a great clip,
its own scoring rubric, and its own prompt templates.
"""

# ─── Available Genres ─────────────────────────────────────────

GENRE_LIST = [
    {"id": "business",         "label": "Business & Entrepreneurship", "clip_length": "45–90s"},
    {"id": "self_improvement",  "label": "Self-Improvement & Mindset",  "clip_length": "30–75s"},
    {"id": "finance",          "label": "Finance & Investing",          "clip_length": "45–90s"},
    {"id": "health",           "label": "Health & Fitness",             "clip_length": "30–60s"},
    {"id": "relationships",    "label": "Relationships & Dating",       "clip_length": "30–60s"},
    {"id": "true_crime",       "label": "True Crime & Storytelling",    "clip_length": "60–90s"},
]


def get_available_genres() -> list:
    """Return list of available genre options."""
    return GENRE_LIST


# ─── Discovery Prompt (Shared — Pass 1) ──────────────────────

DISCOVERY_SYSTEM_PROMPT = """You are an expert short-form content editor specializing in {genre} content.
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
{{
  "candidates": [
    {{
      "block_id": 12,
      "start": 145.3,
      "end": 198.7,
      "hook_preview": "First sentence or two that opens the clip",
      "why_flagged": "One sentence explanation of what makes this promising"
    }}
  ]
}}

Return candidates only. No preamble. No explanation outside the JSON."""


# ─── Scoring Prompt Template (Pass 2) ────────────────────────

SCORING_PROMPT_TEMPLATE = """You are an expert short-form content editor. Score the following clip
candidate against the {genre} scoring criteria below.

CONTEXT BEFORE (not part of the clip):
{context_before}

=== CLIP START ===
{core_text}
=== CLIP END ===

CONTEXT AFTER (not part of the clip):
{context_after}

Clip duration: {duration} seconds

Score this clip on each dimension from 0–10 and return valid JSON only.

{scoring_criteria}

Return ONLY this JSON structure, nothing else:
{{
  "hook_score": 0,
  "hook_analysis": "What works or doesn't about the opening",
  "narrative_score": 0,
  "narrative_analysis": "Does it have a clear arc",
  "standalone_score": 0,
  "standalone_analysis": "Can it be understood without context",
  "emotional_score": 0,
  "emotional_analysis": "What emotion does it trigger and how strongly",
  "length_score": 0,
  "length_analysis": "Is the length appropriate for this genre",
  "total_score": 0,
  "verdict": "STRONG",
  "suggested_trim_start": 0,
  "suggested_trim_end": 0,
  "suggested_title": "A punchy title for this clip",
  "rejection_reason": ""
}}"""


# ─── Genre Scoring Criteria ──────────────────────────────────

BUSINESS_CRITERIA = """BUSINESS & ENTREPRENEURSHIP SCORING CRITERIA:

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
- Promotes a specific product/service in a way that feels like an ad"""


SELF_IMPROVEMENT_CRITERIA = """SELF-IMPROVEMENT & MINDSET SCORING CRITERIA:

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
- Requires knowing who the speaker is to appreciate the story"""


FINANCE_CRITERIA = """FINANCE & INVESTING SCORING CRITERIA:

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
- Contains complex terminology that needs a 30-second explainer"""


HEALTH_CRITERIA = """HEALTH & FITNESS SCORING CRITERIA:

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
- Contradicts basic established medical science without qualification"""


RELATIONSHIPS_CRITERIA = """RELATIONSHIPS & DATING SCORING CRITERIA:

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
- Ends on ambiguity — no clear insight or takeaway"""


TRUE_CRIME_CRITERIA = """TRUE CRIME & STORYTELLING SCORING CRITERIA:

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
- References images or maps the viewer can't see"""


# ─── Genre Profiles Registry ─────────────────────────────────

GENRE_PROFILES = {
    "business": {
        "label": "Business & Entrepreneurship",
        "scoring_criteria": BUSINESS_CRITERIA,
        "ideal_clip_length": (45, 90),
    },
    "self_improvement": {
        "label": "Self-Improvement & Mindset",
        "scoring_criteria": SELF_IMPROVEMENT_CRITERIA,
        "ideal_clip_length": (30, 75),
    },
    "finance": {
        "label": "Finance & Investing",
        "scoring_criteria": FINANCE_CRITERIA,
        "ideal_clip_length": (45, 90),
    },
    "health": {
        "label": "Health & Fitness",
        "scoring_criteria": HEALTH_CRITERIA,
        "ideal_clip_length": (30, 60),
    },
    "relationships": {
        "label": "Relationships & Dating",
        "scoring_criteria": RELATIONSHIPS_CRITERIA,
        "ideal_clip_length": (30, 60),
    },
    "true_crime": {
        "label": "True Crime & Storytelling",
        "scoring_criteria": TRUE_CRIME_CRITERIA,
        "ideal_clip_length": (60, 90),
    },
}
