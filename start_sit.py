#!/usr/bin/env python3
"""
Compare fantasy football starters using ESPN projections/rankings and NFL matchups
Run from the repository root: python start_sit.py
"""

from __future__ import annotations
import argparse
import difflib
import json
import re
import sys
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_FANTASY_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"
POSITIONS = {"WR": "WR", "TE": "TE", "RB": "RB", "QB": "QB", "FLEX": "FLX", "K": "K", "D": "DST", "DST": "DST", "HC": "HC"}
SCORING = {"PPR": "PPR", "STANDARD": "STD", "HALF PPR": "HALF", "0.5 PPR": "HALF", ".5 PPR": "HALF"}
ESPN_TEAM_CODES = {1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"}
ESPN_POSITION_CODES = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
ESPN_SCORING_IDS = {"STD": 1, "HALF": 4, "PPR": 3}

def season_year(today: date | None = None) -> int:
    """
    Return the NFL season year for a date

    Args:
        today: date | None -- date used to determine the NFL season

    Returns:
        int -- NFL season year
    """
    today = today or date.today()
    return today.year if today.month >= 3 else today.year - 1

def get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    """
    Fetch and decode a JSON response

    Args:
        url: str -- request URL
        headers: dict[str, str] | None -- optional HTTP request headers

    Returns:
        dict -- decoded JSON response
    """
    request = Request(url, headers={"User-Agent": "football-start-sit/1.0", **(headers or {})})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(f"The data provider rejected the request for {url}") from exc
        raise RuntimeError(f"Data provider returned HTTP {exc.code} for {url}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not retrieve data: {exc}") from exc

def get_week(season: int) -> int:
    """
    Get the current regular season week from ESPN

    Args:
        season: int -- NFL season year

    Returns:
        int -- current NFL week
    """
    data = get_json(f"{ESPN_SCOREBOARD}?{urlencode({'season': season, 'seasontype': 2})}")
    return int(data.get("week", {}).get("number", 1))

def get_games(season: int, week: int) -> list[dict]:
    """
    Get weekly NFL games and available team scoring lines

    Args:
        season: int -- NFL season year
        week: int -- NFL week number

    Returns:
        list[dict] -- games with teams, dates, and implied scoring totals
    """
    params = urlencode({"season": season, "seasontype": 2, "week": week})
    data = get_json(f"{ESPN_SCOREBOARD}?{params}")
    games = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((x for x in competitors if x.get("homeAway") == "home"), {})
        away = next((x for x in competitors if x.get("homeAway") == "away"), {})
        odds = (comp.get("odds") or [{}])[0]
        try:
            total = float(odds.get("overUnder"))
            raw_spread = float((odds.get("homeTeamOdds") or {}).get("spread"))
            spread = abs(raw_spread)
            home_total, away_total = total / 2 - spread / 2, total / 2 + spread / 2
            home_favored = (odds.get("homeTeamOdds") or {}).get("favorite")
            if home_favored is True or (home_favored is None and raw_spread < 0):
                home_total, away_total = total / 2 + spread / 2, total / 2 - spread / 2
        except (TypeError, ValueError):
            home_total = away_total = None
        games.append({"home": home.get("team", {}).get("abbreviation", ""), "away": away.get("team", {}).get("abbreviation", ""), "date": event.get("date", ""), "name": event.get("name", ""), "home_total": home_total, "away_total": away_total})
    return games

def espn_fantasy_players(season: int, week: int, scoring: str) -> list[dict]:
    """
    Fetch weekly player projections and rankings from ESPN's public fantasy data

    Args:
        season: int -- NFL season year
        week: int -- NFL week number
        scoring: str -- ESPN scoring identifier STD, HALF, or PPR

    Returns:
        list[dict] -- normalized players with projections and positional rankings
    """
    scoring_id = ESPN_SCORING_IDS.get(scoring)
    if scoring_id is None:
        raise RuntimeError(f"ESPN scoring preset is not configured for {scoring}.")
    url = f"{ESPN_FANTASY_BASE}/{season}/segments/0/leaguedefaults/{scoring_id}?{urlencode({'view': 'kona_player_info', 'scoringPeriodId': week})}"
    player_filter = {
        "players": {
            "filterActive": {"value": True},
            "filterRanksForScoringPeriodIds": {"value": [week]},
            "limit": 3000,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }
    }
    data = get_json(url, headers={"X-Fantasy-Filter": json.dumps(player_filter)})
    results = []
    for entry in data.get("players", []):
        player = entry.get("player", {})
        player_stats = player.get("stats") or (entry.get("playerPoolEntry") or {}).get("stats", [])
        projection = next((stat for stat in player_stats if stat.get("seasonId") == season and stat.get("scoringPeriodId") == week and stat.get("statSourceId") == 1 and stat.get("statSplitTypeId") == 1), None)
        if projection is None:
            continue
        try:
            points = float(projection.get("appliedTotal"))
        except (TypeError, ValueError):
            continue
        position_id = ESPN_POSITION_CODES.get(player.get("defaultPositionId"), "")
        weekly_rankings = (player.get("rankings") or entry.get("rankings") or {}).get(str(week), [])
        ranking_type = {"PPR": "PPR", "STD": "STANDARD", "HALF": "HALF_PPR"}[scoring]
        rank_values = [float(rank["rank"]) for rank in weekly_rankings if rank.get("rankType") == ranking_type and rank.get("rank") is not None and (rank.get("slotId") == {"QB": 0, "RB": 2, "WR": 4, "TE": 6, "K": 17, "DST": 16}.get(position_id, rank.get("slotId")))]
        if not rank_values:
            ratings = entry.get("ratings") or {}
            rank_values = [float(item["positionalRanking"]) for item in ratings.values() if item.get("positionalRanking")]
        rank = sum(rank_values) / len(rank_values) if rank_values else None
        results.append({
            "player_name": player.get("fullName") or player.get("name") or "",
            "team": ESPN_TEAM_CODES.get(player.get("proTeamId"), ""),
            "position_id": position_id,
            "points": points,
            "rank_ecr": rank,
            "injury_status": player.get("injuryStatus", "ACTIVE"),
        })
    if not results:
        raise RuntimeError(f"ESPN returned no weekly projections for {season} Week {week} ({scoring}). The week may not be published yet.")
    return results

def clean_name(value: str) -> str:
    """
    Normalize a player name for matching

    Args:
        value: str -- player name to normalize

    Returns:
        str -- lowercase name containing letters and spaces
    """
    return re.sub(r"[^a-z0-9 ]", "", value.casefold()).strip()

def choose_player(name: str, rows: list[dict]) -> dict:
    """
    Find an exact or close player name match

    Args:
        name: str -- player name entered by the user
        rows: list[dict] -- player records to search

    Returns:
        dict -- matched player record
    """
    names = [str(row.get("player_name") or row.get("name") or "") for row in rows]
    normalized = {clean_name(n): n for n in names}
    key = clean_name(name)
    match = normalized.get(key)
    if match:
        return next(x for x in rows if (x.get("player_name") or x.get("name")) == match)
    close = difflib.get_close_matches(key, list(normalized), n=3, cutoff=0.55)
    suggestions = [normalized[x] for x in close]
    if suggestions:
        raise ValueError(f"Couldn't find '{name}'. Did you mean: {', '.join(suggestions)}?")
    raise ValueError(f"Couldn't find '{name}' in the provider's current player data.")

def get_projection_points(row: dict, scoring: str) -> float | None:
    """
    Read fantasy points for the selected scoring format

    Args:
        row: dict -- FantasyPros player projection record
        scoring: str -- scoring format identifier

    Returns:
        float | None -- projected fantasy points when available
    """
    try:
        return float(row["points"])
    except (KeyError, TypeError, ValueError):
        return None

def matchup_by_team(games: list[dict]) -> tuple[dict[str, str], dict[str, float]]:
    """
    Build team matchup and implied scoring lookups

    Args:
        games: list[dict] -- weekly games from the scoreboard

    Returns:
        tuple[dict[str, str], dict[str, float]] -- opponent labels and team scoring totals
    """
    result = {}
    team_totals = {}
    for game in games:
        if game["home"] and game["away"]:
            result[game["home"]] = f"vs {game['away']}"
            result[game["away"]] = f"@ {game['home']}"
            if game["home_total"] is not None:
                team_totals[game["home"]] = game["home_total"]
                team_totals[game["away"]] = game["away_total"]
    return result, team_totals

def main(players: str | None = None, position: str | None = None, week: int | None = None, scoring: str | None = None) -> int:
    """
    Run the start or sit recommendation workflow

    Args:
        players: str | None -- comma-separated player names
        position: str | None -- fantasy position for the comparison
        week: int | None -- NFL week to evaluate
        scoring: str | None -- fantasy scoring format

    Returns:
        int -- process exit status
    """
    parser = argparse.ArgumentParser(description="Compare fantasy starters using weekly projections, rankings, and NFL matchups.")
    parser.add_argument("--players", help="Comma-separated player names. If omitted, you'll be prompted.")
    parser.add_argument("--position", help="WR, TE, RB, QB, Flex, K, D/DST, or HC")
    parser.add_argument("--week", type=int, help="NFL week (defaults to ESPN's current regular-season week)")
    parser.add_argument("--type", dest="scoring", help="PPR (default), standard, or half PPR")
    args = parser.parse_args()

    names_text = args.players or players or input("Players (comma-separated): ")
    names = [x.strip() for x in names_text.split(",") if x.strip()]
    if len(names) < 2:
        parser.error("Enter at least two comma-separated players.")
    pos_key = (args.position or position or "FLEX").strip().upper()
    position = POSITIONS.get(pos_key)
    if not position:
        parser.error("Position must be WR, TE, RB, QB, Flex, K, D/DST, or HC.")
    scoring_key = re.sub(r"\s+", " ", (args.scoring or scoring or "PPR").strip().upper())
    scoring = SCORING.get(scoring_key)
    if not scoring:
        parser.error("Type must be PPR, standard, half PPR, 0.5 PPR, or .5 PPR.")
    season = season_year()
    try:
        selected_week = args.week or week or get_week(season)
        if not 1 <= selected_week <= 18:
            parser.error("Week must be from 1 to 18.")
        player_data = espn_fantasy_players(season, selected_week, scoring)
        games = get_games(season, selected_week)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    matchups, team_totals = matchup_by_team(games)
    results = []
    for name in names:
        try:
            projection = choose_player(name, player_data)
            if position != "FLX" and projection.get("position_id") != position:
                raise ValueError(f"{projection['player_name']} is listed as {projection.get('position_id')}, not {pos_key}.")
            points = get_projection_points(projection, scoring)
            if points is None:
                raise ValueError(f"No {scoring} projection was returned for {name}.")
            rank_num = projection.get("rank_ecr")
            try:
                rank_num = float(rank_num)
            except (TypeError, ValueError):
                rank_num = None
            team = str(projection.get("team") or "")
            team_total = team_totals.get(team)
            # Use sportsbook-implied team scoring as a small game-environment adjustment.
            # Clamp to avoid letting noisy market lines overwhelm the player projection.
            multiplier = max(0.88, min(1.12, 1 + ((team_total - 22) * 0.008))) if team_total is not None else 1.0
            results.append({"name": projection.get("player_name") or projection.get("name") or name, "position": projection.get("position_id", "?"), "team": team, "matchup": matchups.get(team, "bye / matchup unavailable"), "points": points, "adjusted": points * multiplier, "rank": rank_num})
        except ValueError as exc:
            print(f"Warning: {exc}", file=sys.stderr)

    if not results:
        print("No entered players could be matched to both a projection and ranking.", file=sys.stderr)
        return 1
    max_points = max((x["adjusted"] for x in results), default=0) or 1
    position_rank_max = {
        player_position: max((row["rank_ecr"] for row in player_data if row["position_id"] == player_position and row.get("rank_ecr")), default=1)
        for player_position in {row["position_id"] for row in player_data}
    }
    for item in results:
        model_score = max(0.0, min(100.0, 100 * item["adjusted"] / max_points))
        max_rank = position_rank_max.get(item["position"], 1)
        rank_score = 100 * (1 - ((item["rank"] or max_rank) - 1) / max(max_rank - 1, 1))
        rank_score = max(0.0, min(100.0, rank_score))
        item["score"] = 0.7 * model_score + 0.3 * rank_score
    results.sort(key=lambda x: x["score"], reverse=True)
    print(f"\nWeek {selected_week} | {season} | {scoring} scoring | Position: {pos_key}\n")
    print(f"{'Player':25} {'Pos':4} {'Opp':18} {'Proj':>7} {'Adj':>7} {'Rank':>6} {'Score':>7}")
    print("-" * 73)
    for x in results:
        rank = f"{x['rank']:.0f}" if x["rank"] is not None else "—"
        print(f"{x['name'][:25]:25} {x['position'][:4]:4} {x['matchup'][:18]:18} {x['points']:7.1f} {x['adjusted']:7.1f} {rank:>6} {x['score']:7.1f}")
    print(f"\nRecommendation: Start {results[0]['name']} (highest blended comparison score).")
    print("Score blends 70% relative ESPN weekly projections (with a small ESPN odds-based team scoring adjustment) and 30% relative ESPN positional rank; it is a comparison aid, not a guaranteed outcome.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(
        players="Dak Prescott, Patrick Mahomes",
        position="QB",
        week=7,
        scoring="PPR",
    ))
