# NFL Fantasy Football Tools

Four command-line Python scripts for weekly fantasy lineup decisions, NFL game winner picks, fantasy trade analysis, and draft-candidate comparisons.

## Requirements

- Python 3.10 or newer
- Internet access

The scripts use only Python's standard library; no `pip install` is needed.

## Start / sit recommendation

Run from the repository directory:

```bash
python start_sit.py --players "Rachaad White, JK Dobbins" --position flex --week 6 --type PPR
```

You can also edit the settings in the `if __name__ == "__main__":` block at the bottom of `start_sit.py` and run `python start_sit.py`:

```python
raise SystemExit(main(
    players="Rachaad White, JK Dobbins",
    position="Flex",
    week=6,
    scoring="PPR",
))
```

Use `players=None`, `position=None`, `week=None`, or `scoring=None` to use the prompt or default for that setting. Command-line options override the values in this block.

Arguments:

- `--players`: comma-separated names; if omitted from both the command line and the editable settings block, the script prompts for them. Near matches produce spelling suggestions.
- `--position`: `WR`, `TE`, `RB`, `QB`, `Flex`, `K`, `D`/`DST`, or `HC`. Case-insensitive; defaults to `Flex`.
- `--week`: NFL week 1–18; defaults to the current week reported by ESPN's scoreboard.
- `--type`: `PPR` (default), `standard`, or `half PPR` (also accepts `0.5 PPR` and `.5 PPR`). Case-insensitive.

The script uses ESPN's public fantasy player-data endpoint for weekly projections, player names, injuries, and positional rankings, so it does not need a FantasyPros API key. It also displays the ESPN schedule matchup and applies a small adjustment to the projection when ESPN supplies betting-implied team scoring for that game. The comparison score gives 70% weight to relative adjusted projections and 30% to relative ESPN positional rank. A higher score is a recommendation aid, not a certainty. ESPN projection availability can vary by week and scoring format.

The usual fantasy defense position is `D` or `DST`. FantasyPros does not reliably publish weekly player projections for `HC`; the script reports this if that position is selected.

## Weekly game winner predictions

```bash
python predict_games.py --week 6
```

Or set the week in the `if __name__ == "__main__":` block at the bottom of `predict_games.py`:

```python
raise SystemExit(main(week=6))
```

Use `week=None` for ESPN's current week. A `--week` command-line option overrides the value in the block.

Omit the week to use ESPN's current regular-season week:

```bash
python predict_games.py
```

This script builds simple team Elo ratings from completed games in earlier weeks of the current season, with a 55-point home-field adjustment. It also applies a capped team penalty from ESPN injury statuses, with a larger weight for quarterbacks and players marked out or on injured reserve. It blends the model's win probability equally with the ESPN-listed implied moneyline probability when available. Without market odds, it uses the model alone. The injury adjustment is a simple heuristic and does not identify every player's starter status, so review the displayed odds and injury report before relying on a pick.

## Fantasy trade analyzer

Run the interactive analyzer:

```bash
python trade_analyzer.py
```

Enter each team's incoming assets on its own line, then press Enter on a blank line to analyze the trade. For example:

```text
Team and assets: Team A: Bijan Robinson, 2027 1st early
Team and assets: Team B: Patrick Mahomes, 2027 2nd mid
Team and assets:
```

You can also pass all teams on the command line. Repeat `--team` once for each trade participant:

```bash
python trade_analyzer.py --team "Team A=Bijan Robinson, 2027 1st early" --team "Team B=Patrick Mahomes, 2027 2nd mid" --type PPR --format dynasty
```

Or edit the `main()` call at the bottom of `trade_analyzer.py`:

```python
raise SystemExit(main(
    teams={
        "Team A": "Bijan Robinson, 2027 1st early",
        "Team B": "Patrick Mahomes, 2027 2nd mid",
    },
    scoring="PPR",
    week=None,
    league_format="dynasty",
))
```

Use two or more teams. Team package assets are comma-separated player names and/or picks. Player names match case-insensitively, and close misspellings produce suggestions like the start/sit tool. Picks can be written as `2027 1st early`, `2nd mid`, or `3rd late`; an omitted year is allowed, and an omitted tier defaults to mid. Supported scoring labels are PPR, standard, and half PPR. Set `--format` to `standard` (default) or `dynasty`; this is separate from scoring format. Week defaults to ESPN's current regular-season week and selects the ESPN player-ranking snapshot.

The report gives each team an overall score from 0–100, where higher means that team receives more estimated trade value; the team receiving the most value scores 100. Player values use ESPN's projected rest-of-season fantasy points minus an estimated replacement starter at the same position. Replacement levels assume a 12-team, one-quarterback league (QB 13, RB 25, WR 37, TE 13); this approximates positional scarcity and helps compare RBs and TEs on a common basis. If season projections are unavailable, it falls back to positional rank. Package totals apply diminishing returns to additional assets, so a bundle of lower-value players does not automatically outweigh one elite player. Trades within 10% are rated fair, within 25% are rated slightly uneven, and larger gaps are rated unfair. Draft picks use configurable values in `PICK_VALUES`; dynasty mode uses lower pick values in `DYNASTY_PICK_VALUES`, calibrated to the current-season player scale. Dynasty player values remain rest-of-season estimates because ESPN data here does not provide age or multi-year projections, so this is only a short-term lens for dynasty trades.

## Draft analyzer

Compare two or more players you are considering drafting:

```bash
python draft_analyzer.py --players "Bijan Robinson, CeeDee Lamb, Patrick Mahomes" --type PPR
```

If `--players` is omitted, the script prompts for names. Use `--type` for `PPR` (default), `standard`, or `half PPR` (also accepts `0.5 PPR` and `.5 PPR`). An optional `--week` selects the current-season ESPN projection and ranking snapshot; if omitted, it uses ESPN's current regular-season week. The season year defaults to the current NFL season. Names are case-insensitive and close misspellings produce spelling suggestions.

You can also edit the settings in the `if __name__ == "__main__":` block at the bottom of `draft_analyzer.py` and run `python draft_analyzer.py`:

```python
raise SystemExit(main(
    players="Bijan Robinson, CeeDee Lamb, Patrick Mahomes",
    scoring="PPR",
    week=None,
))
```

The analyzer prints each matched player's projected points, ESPN positional rank, and a comparative 0–100 score. The score combines 70% relative projected points and 30% relative positional rank among the available ESPN player data, then recommends the highest-scoring option. It is a guide rather than a full draft strategy and does not account for roster needs, draft position, or future-season development.

## Data sources

- [ESPN public fantasy data](https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leaguedefaults/3?view=kona_player_info) — weekly projections, player metadata, and ranking data used by the start/sit, trade, and draft tools. No ESPN account or FantasyPros API key is required.
- [ESPN NFL scoreboard API](https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard) — current schedule, results, and available game odds.
- [ESPN NFL injuries](https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries) — current league-wide injury report used by game predictions.

Data availability, ranking updates, injury reports, and odds coverage vary by week. The scripts report provider or missing-data errors rather than inventing unavailable player projections.
