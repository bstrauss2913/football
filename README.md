# NFL Fantasy Football Tools

Two command-line Python scripts for weekly fantasy lineup decisions and NFL game winner picks.

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

## Data sources

- [ESPN public fantasy data](https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leaguedefaults/3?view=kona_player_info) — weekly projections, player metadata, and ranking data. No ESPN account or FantasyPros API key is required.
- [ESPN NFL scoreboard API](https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard) — current schedule, results, and available game odds.
- [ESPN NFL injuries](https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries) — current league-wide injury report used by game predictions.

Data availability, ranking updates, injury reports, and odds coverage vary by week. The scripts report provider or missing-data errors rather than inventing unavailable player projections.
