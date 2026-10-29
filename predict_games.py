#!/usr/bin/env python3
"""
Predict weekly NFL game winners with a simple Elo model and ESPN market odds
Run from the repository root: python predict_games.py
"""

from __future__ import annotations
import argparse
import json
import sys
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"

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

def scoreboard(season: int, week: int | None = None) -> dict:
    """
    Fetch the ESPN NFL scoreboard for a season and optional week

    Args:
        season: int -- NFL season year
        week: int | None -- optional NFL week number

    Returns:
        dict -- decoded ESPN scoreboard response
    """
    params = {"season": season, "seasontype": 2}
    if week is not None:
        params["week"] = week
    request = Request(f"{ESPN_SCOREBOARD}?{urlencode(params)}", headers={"User-Agent": "football-picks/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not retrieve ESPN scoreboard: {exc}") from exc

def injury_report() -> dict:
    """
    Fetch the current ESPN NFL injury report

    Args:
        None -- this function takes no arguments

    Returns:
        dict -- decoded ESPN league injury report
    """
    request = Request(ESPN_INJURIES, headers={"User-Agent": "football-picks/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not retrieve ESPN injury report: {exc}") from exc

def win_probability(rating_diff: float) -> float:
    """
    Convert an Elo rating difference to a win probability

    Args:
        rating_diff: float -- rating difference including home advantage

    Returns:
        float -- estimated probability from zero to one
    """
    return 1 / (1 + 10 ** (-rating_diff / 400))

def games_from(data: dict) -> list[dict]:
    """
    Extract games with home and away team records

    Args:
        data: dict -- decoded ESPN scoreboard response

    Returns:
        list[dict] -- game records with teams and odds data
    """
    games = []
    for event in data.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors", [])
        home = next((x for x in competitors if x.get("homeAway") == "home"), {})
        away = next((x for x in competitors if x.get("homeAway") == "away"), {})
        if not home.get("team") or not away.get("team"):
            continue
        games.append({"home": home, "away": away, "event": event, "competition": competition})
    return games

def injury_cost(status: str, position: str) -> float:
    """
    Estimate a team's Elo penalty for an injured player

    Args:
        status: str -- ESPN injury or game status
        position: str -- player position abbreviation

    Returns:
        float -- negative Elo adjustment for the team
    """
    status = status.upper().replace("_", " ")
    if "INJURY RESERVE" in status or status in {"OUT", "SUSPENDED", "IR"}:
        severity = 1.0
    elif "DOUBTFUL" in status:
        severity = 0.65
    elif "QUESTIONABLE" in status or "DAY TO DAY" in status:
        severity = 0.3
    else:
        return 0.0
    position = position.upper()
    weight = {"QB": 42.0, "RB": 7.0, "WR": 5.5, "TE": 5.0, "T": 4.0, "OT": 4.0, "G": 3.5, "OG": 3.5, "C": 3.5, "K": 1.0}.get(position, 2.5)
    return -weight * severity

def injury_adjustments(data: dict) -> dict[str, float]:
    """
    Aggregate current injuries into team Elo adjustments

    Args:
        data: dict -- ESPN league injury report

    Returns:
        dict[str, float] -- team abbreviations mapped to negative Elo adjustments
    """
    adjustments: dict[str, float] = {}
    seen: set[tuple[str, str]] = set()
    pending = [(data, "")]
    while pending:
        current, inherited_team = pending.pop()
        if isinstance(current, list):
            pending.extend((item, inherited_team) for item in current)
            continue
        if not isinstance(current, dict):
            continue
        team_data = current.get("team")
        team = inherited_team
        if isinstance(team_data, dict):
            team = str(team_data.get("abbreviation") or team_data.get("shortDisplayName") or team)
        elif isinstance(team_data, str):
            team = team_data
        athlete = current.get("athlete") or current.get("player")
        if isinstance(athlete, dict):
            position_data = athlete.get("position") or {}
            position = position_data.get("abbreviation", "") if isinstance(position_data, dict) else str(position_data)
            fantasy = current.get("fantasy") or {}
            status = current.get("status") or current.get("gameStatus") or (fantasy.get("status") if isinstance(fantasy, dict) else "") or athlete.get("injuryStatus", "")
            player_id = str(athlete.get("id") or athlete.get("displayName") or athlete.get("fullName") or "")
            key = (team, player_id)
            if team and player_id and key not in seen:
                seen.add(key)
                adjustments[team] = adjustments.get(team, 0.0) + injury_cost(str(status), str(position))
        for value in current.values():
            if isinstance(value, (dict, list)):
                pending.append((value, team))
    return {team: max(-85.0, penalty) for team, penalty in adjustments.items()}

def update_elo(ratings: dict[str, float], home: dict, away: dict) -> None:
    """
    Update both teams Elo ratings from a completed game

    Args:
        ratings: dict[str, float] -- team abbreviations mapped to Elo ratings
        home: dict -- home competitor record
        away: dict -- away competitor record

    Returns:
        None -- updates the ratings mapping in place
    """
    if not home.get("score") or not away.get("score"):
        return
    hs, aws = float(home["score"]), float(away["score"])
    hname, aname = home["team"]["abbreviation"], away["team"]["abbreviation"]
    hr, ar = ratings.get(hname, 1500), ratings.get(aname, 1500)
    expected_home = win_probability(hr + 55 - ar)
    result_home = 1.0 if hs > aws else 0.0 if hs < aws else 0.5
    k = 24 * min(2.0, 1 + abs(hs - aws) / 28)
    ratings[hname] = hr + k * (result_home - expected_home)
    ratings[aname] = ar - k * (result_home - expected_home)

def moneyline_probability(game: dict) -> float | None:
    """
    Calculate the home win probability implied by moneyline odds

    Args:
        game: dict -- game record containing competition odds

    Returns:
        float | None -- normalized home probability when odds are available
    """
    odds_list = game["competition"].get("odds") or []
    if not odds_list:
        return None
    odds = odds_list[0]
    home_odds = (odds.get("homeTeamOdds") or {}).get("moneyLine")
    away_odds = (odds.get("awayTeamOdds") or {}).get("moneyLine")
    try:
        def implied(value: float) -> float:
            value = float(value)
            return 100 / (100 + value) if value > 0 else abs(value) / (abs(value) + 100)
        hp, ap = implied(home_odds), implied(away_odds)
        return hp / (hp + ap)
    except (TypeError, ValueError, ZeroDivisionError):
        return None

def main(week: int | None = None) -> int:
    """
    Run the weekly NFL winner prediction workflow

    Args:
        week: int | None -- NFL week to predict

    Returns:
        int -- process exit status
    """
    parser = argparse.ArgumentParser(description="Predict NFL game winners for a week using team Elo and ESPN betting odds.")
    parser.add_argument("--week", type=int, help="NFL week (defaults to ESPN's current regular-season week)")
    args = parser.parse_args()
    season = season_year()
    try:
        current = scoreboard(season)
        selected_week = args.week or week or int(current.get("week", {}).get("number", 1))
        if not 1 <= selected_week <= 18:
            parser.error("Week must be from 1 to 18.")
        ratings: dict[str, float] = {}
        # Update ratings in week order using only completed games before the target week.
        for prior_week in range(1, selected_week):
            for game in games_from(scoreboard(season, prior_week)):
                update_elo(ratings, game["home"], game["away"])
        target_games = games_from(scoreboard(season, selected_week))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        injuries = injury_adjustments(injury_report())
    except RuntimeError as exc:
        print(f"Warning: {exc}; continuing without injury adjustments", file=sys.stderr)
        injuries = {}

    if not target_games:
        print(f"No games returned for {season} Week {selected_week}. The schedule may not be available yet.")
        return 0
    print(f"\nNFL {season} Week {selected_week} winner predictions\n")
    print(f"{'Matchup':34} {'Model H%':>8} {'Market H%':>9} {'Inj Δ':>7} {'Pick':20} {'Win %':>7}")
    print("-" * 81)
    for game in target_games:
        home, away = game["home"]["team"], game["away"]["team"]
        h, a = home["abbreviation"], away["abbreviation"]
        injury_delta = injuries.get(h, 0.0) - injuries.get(a, 0.0)
        model_home = win_probability(ratings.get(h, 1500) + 55 - ratings.get(a, 1500) + injury_delta)
        market_home = moneyline_probability(game)
        final_home = 0.5 * model_home + 0.5 * market_home if market_home is not None else model_home
        home_pick = final_home >= 0.5
        winner = home if home_pick else away
        confidence = final_home if home_pick else 1 - final_home
        model_label = f"{model_home * 100:7.1f}%"
        market_label = f"{market_home * 100:8.1f}%" if market_home is not None else "n/a"
        matchup = f"{away['displayName']} @ {home['displayName']}"
        print(f"{matchup[:34]:34} {model_label:>8} {market_label:>9} {injury_delta:7.1f} {winner['displayName'][:20]:20} {confidence * 100:6.1f}%")
    print("\nModel: Elo ratings start at 1500, update on completed regular-season results, and include 55 home-field points and ESPN injury adjustments.")
    print("Final pick blends model probability 50/50 with ESPN's implied moneyline probability when odds are available; otherwise it uses the model alone.")
    print("Inj Δ is the home team's injury Elo adjustment minus the away team's adjustment; each team penalty is capped at 85 Elo points.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(
        week=8
    ))
