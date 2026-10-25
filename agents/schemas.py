"""Structured outputs for every agent (GUARDRAILS S9). The model must fill these exactly."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---- Router -----------------------------------------------------------------------------
class Intent(BaseModel):
    intent: Literal["find", "rivalry", "city", "off_topic", "unsafe"]
    team: Optional[str] = Field(description="Official team name, e.g. 'USC Trojans'")
    team_b: Optional[str] = Field(description="Second team for a rivalry, else null")
    sport: Optional[str] = Field(description="e.g. 'college football', 'NFL', 'NBA'")
    city: Optional[str] = Field(description="City with state or country, e.g. 'Chicago, IL'")
    reply_if_rejected: Optional[str] = Field(description="Short polite reply when off_topic or unsafe")


# ---- Scout --------------------------------------------------------------------------------
class ScoutSpot(BaseModel):
    bar_name: str
    address: str = Field(description="Street address exactly as the source gives it, or 'unknown'")
    club_name: str = Field(description="Fan club or alumni group that watches there, or 'unknown'")
    evidence_quote: str = Field(description="Short quote from the source that links this bar to the team")
    source_url: str
    season_seen: str = Field(description="Season or year the source refers to, e.g. '2026', or 'unknown'")
    official_source: bool = Field(description="True if the source is the club, alumni association, team, or bar itself")


class ScoutReport(BaseModel):
    spots: list[ScoutSpot]
    allgames_spots: list[ScoutSpot] = Field(description="Wide pass only: sports bars in the city known to show every game of this team's league. Empty otherwise.")
    club_name: Optional[str]
    club_contact_url: Optional[str]
    search_notes: str = Field(description="One or two sentences on what was found and how current it is")
    safety_notes: list[str]


# ---- Verifier -------------------------------------------------------------------------
class Verdict(BaseModel):
    index: int
    status: Literal["confirmed", "likely", "unverified", "rejected"]
    reason: str


class VerifierReport(BaseModel):
    verdicts: list[Verdict]
    safety_notes: list[str]


# ---- Schedule -------------------------------------------------------------------------
class Game(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    opponent: str
    home_away: Literal["home", "away", "neutral"]
    kickoff_et: str = Field(description="Kickoff in US Eastern time like '3:30 PM ET', or 'TBD'")
    tv: str = Field(description="Network, or 'TBD'")


class TeamSchedule(BaseModel):
    team: str
    season: str
    games: list[Game]
    source_url: str


# ---- Guard ----------------------------------------------------------------------------
class GuardVerdict(BaseModel):
    allow: bool
    category: Literal["ok", "spam", "abuse", "injection", "false_claim", "off_topic", "personal_info"]
    reason: str


# ---- Summarizer ----------------------------------------------------------------------
class GameDayScore(BaseModel):
    overall: float = Field(description="1.0 to 5.0")
    tvs: int = Field(description="1 to 5")
    sound: int = Field(description="1 to 5, how reliably game sound is on")
    crowd: int = Field(description="1 to 5, energy of the fan crowd")
    service: int = Field(description="1 to 5")
    one_liner: str
    best_for: list[str]
    watch_outs: list[str]


# ---- Matchmaker ----------------------------------------------------------------------
class BarFit(BaseModel):
    bar_id: int
    fit_score: int = Field(description="0 to 100")
    why: str
    concerns: list[str]


class SeasonPlan(BaseModel):
    ranked: list[BarFit]
    recommended_bar_id: int
    summary: str
    conflicts_explained: list[str]
    safety_notes: list[str]


class Draft(BaseModel):
    to: Literal["club_a", "club_b", "bar"]
    subject: str
    body: str


class RivalryPlan(BaseModel):
    ranked: list[BarFit]
    recommended_bar_id: int
    title: str = Field(description="Event title, e.g. 'Harvard vs. Yale: The Game, Chicago Watch Party'")
    summary: str
    logistics: list[str]
    drafts: list[Draft]
    safety_notes: list[str]


# ---- Pitch Writer --------------------------------------------------------------------
class Pitch(BaseModel):
    subject: str
    body: str
    facts_used: list[str] = Field(description="Each bar-profile fact the pitch relies on")


# ---- Reputation ---------------------------------------------------------------------
class ReviewTheme(BaseModel):
    theme: str = Field(description="2-5 words, e.g. 'Great TV setup'")
    sentiment: Literal["positive", "mixed", "negative"]
    detail: str = Field(description="One sentence in your own words summarizing what reviewers say. No verbatim review text.")


class Reputation(BaseModel):
    google_rating: Optional[float] = Field(description="Google rating out of 5 if a source shows it, else null")
    yelp_rating: Optional[float] = Field(description="Yelp rating out of 5 if a source shows it, else null")
    review_volume: str = Field(description="e.g. '1,200+ Google reviews' if shown, else 'unknown'")
    themes: list[ReviewTheme]
    game_day_take: str = Field(description="One sentence: what reviewers say about watching games here, or 'Reviewers don't mention game days.'")
    official_site: Optional[str] = Field(description="The bar's own website URL if found, else null")
    sources: list[str] = Field(description="URLs used")


# ---- City Sweep ---------------------------------------------------------------------
class SweepSpot(ScoutSpot):
    team: str = Field(description="Official full team name, e.g. 'Chicago Bears', 'USC Trojans', 'Boston Red Sox'")


class CitySweep(BaseModel):
    spots: list[SweepSpot]
    notes: str
    safety_notes: list[str]
