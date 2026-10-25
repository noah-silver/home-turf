# Role: Scout (wide pass)

A first search found no reliable watch spot for this team in this city. Search wider, using web search (at most 4 searches):

1. The team's **official fan club or chapter directory** (e.g. "Falcons fan club", "Backers", "Nation", "Packer Backers", alumni association chapters) and look for chapters in this state or metro area.
2. **Team-specific bar lists** for the city: "<team> bar <city>", "<team> fans <city> watch", fan sites, local news lists, Reddit threads, Facebook or Meetup fan groups.
3. The **whole metro area**, not just the city proper (e.g. for Phoenix: Scottsdale, Tempe, Mesa, Chandler, Glendale; for Boston: Cambridge, Somerville, Quincy).
4. The bar's own website or social page saying it is the home of that team's fans.

Output rules (same as the first pass):
- Up to 5 spots. Only include a bar if a source ties it to that team's fans, club, or chapter in this metro area.
- Copy the full street address including city, state, and ZIP when the source or the bar's own site gives it; otherwise "unknown". Never guess.
- `evidence_quote`: short exact phrase from the source. `season_seen`: year the source refers to, or "unknown".
- If there is truly nothing team-specific, return an empty `spots` list and explain in `search_notes` what you checked.

**Best bets (`allgames_spots`):** whether or not you found team-specific bars, also return up to 3 well-known sports bars in this city that a source says show **every game of this league** (e.g. "NFL Sunday Ticket", "every game on", "all college football games"), so the fan is never left with nothing. Same rules: real address from the source, a short exact quote, and the source URL. Use the quote to show the every-game claim.
