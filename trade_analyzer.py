#!/usr/bin/env python3
"""
Compare fantasy football trade packages using ESPN player rankings and draft pick values
Run from the repository root: python trade_analyzer.py
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from start_sit import choose_player, espn_fantasy_players, get_week, season_year

PICK_VALUES = {
    1: {"early": 55.0, "mid": 45.0, "late": 35.0},
    2: {"early": 22.0, "mid": 16.0, "late": 10.0},
    3: {"early": 8.0, "mid": 5.0, "late": 2.0},
}
POSITION_MULTIPLIERS = {"QB": 0.82, "RB": 1.0, "WR": 0.95, "TE": 0.82, "K": 0.15, "DST": 0.15}
INJURY_MULTIPLIERS = {"ACTIVE": 1.0, "QUESTIONABLE": 0.85, "DOUBTFUL": 0.65, "OUT": 0.45, "INJURY_RESERVE": 0.35, "SUSPENDED": 0.35}
SCORING_OPTIONS = {"PPR": "PPR", "STANDARD": "STD", "STD": "STD", "HALF PPR": "HALF", "HALF_PPR": "HALF", "0.5 PPR": "HALF", ".5 PPR": "HALF"}
DYNASTY_PICK_VALUES = {
    1: {"early": 68.0, "mid": 58.0, "late": 48.0},
    2: {"early": 18.0, "mid": 14.0, "late": 10.0},
    3: {"early": 8.0, "mid": 5.0, "late": 2.0},
}
DYNASTY_POSITION_MULTIPLIERS = {"QB": 1.08, "RB": 0.88, "WR": 1.08, "TE": 1.0, "K": 0.15, "DST": 0.15}
REPLACEMENT_RANKS = {"QB": 13, "RB": 25, "WR": 37, "TE": 13, "K": 13, "DST": 13}
VORP_SCALE = 90.0

def parse_pick(asset: str) -> dict | None:
    """
    Parse a draft pick name with an optional year and draft position tier

    Args:
        asset: str -- trade asset text entered by the user

    Returns:
        dict | None -- normalized pick details or None for a player name
    """
    text = re.sub(r"\s+", " ", asset.strip().casefold())
    pattern = r"^(?:(?P<year>20\d{2})\s+)?(?P<round>1st|first|1|2nd|second|2|3rd|third|3)(?:\s*[- ]?round)?(?:\s+(?:round\s+)?)?(?:\s*[-( ]\s*(?P<tier>early|mid|middle|late)\)?)?(?:\s+pick)?$"
    match = re.fullmatch(pattern, text)
    if not match:
        return None
    round_text = match.group("round")
    round_number = 1 if round_text in {"1st", "first", "1"} else 2 if round_text in {"2nd", "second", "2"} else 3
    tier_text = (match.group("tier") or "mid").replace("middle", "mid")
    return {"year": int(match.group("year")) if match.group("year") else None, "round": round_number, "tier": tier_text}

def pick_value(pick: dict, league_format: str = "standard") -> float:
    """
    Return the configured value for a draft round and pick tier

    Args:
        pick: dict -- normalized draft pick details

    Returns:
        float -- draft pick value on a zero to one hundred scale
    """
    values = DYNASTY_PICK_VALUES if league_format == "dynasty" else PICK_VALUES
    return values[pick["round"]][pick["tier"]]

def replacement_points(players: list[dict]) -> dict[str, float]:
    """
    Estimate replacement starter projections for a 12-team, one-quarterback league

    Args:
          players: list[dict] -- ESPN player records with rest-of-season projections

    Returns:
          dict[str, float] -- replacement projection by player position
    """
    result = {}
    for position, rank in REPLACEMENT_RANKS.items():
        projections = sorted(
            (float(player["season_points"]) for player in players
             if player.get("position_id") == position and player.get("season_points") is not None),
            reverse=True,
        )
        if projections:
            result[position] = projections[min(rank - 1, len(projections) - 1)]
    return result

def player_value(player: dict, league_format: str = "standard", replacements: dict[str, float] | None = None) -> float:
    """
    Estimate a player's current trade value from ESPN's positional ranking and status

    Args:
        player: dict -- normalized ESPN player record
        league_format: str -- standard or dynasty valuation format
        replacements: dict[str, float] | None -- replacement projection by position

    Returns:
        float -- player value on a zero to one hundred scale
    """
    try:
        rank = max(1.0, float(player.get("rank_ecr") or 100.0))
    except (TypeError, ValueError):
        rank = 100.0
    position = player.get("position_id", "")
    position_values = DYNASTY_POSITION_MULTIPLIERS if league_format == "dynasty" else POSITION_MULTIPLIERS
    if player.get("season_points") is not None and replacements and player.get("position_id") in replacements:
        points_above_replacement = max(0.0, float(player["season_points"]) - replacements[player["position_id"]])
        base = 100.0 * (1.0 - math.exp(-points_above_replacement / VORP_SCALE))
    else:
        base = 100.0 * math.exp(-0.04 * (rank - 1)) * position_values.get(position, 0.5)
    status = str(player.get("injury_status") or "ACTIVE").upper().replace(" ", "_")
    return base * INJURY_MULTIPLIERS.get(status, 0.75)

def package_value(assets: list[dict]) -> float:
    """
    Estimate a trade package value with diminishing returns for additional assets

    Args:
          assets: list[dict] -- trade assets with individual values

    Returns:
          float -- adjusted combined package value
    """
    ordered_values = sorted((float(asset["value"]) for asset in assets), reverse=True)
    weights = (1.0, 0.58, 0.38, 0.27, 0.20)
    total = 0.0
    for index, value in enumerate(ordered_values):
        weight = weights[index] if index < len(weights) else 0.15
        total += value * weight
    return total

def parse_team_assets(teams: dict[str, str], players: list[dict], league_format: str = "standard") -> list[dict]:
    """
    Match each team's received assets to picks or ESPN player records

    Args:
        teams: dict[str, str] -- team names mapped to comma-separated incoming assets
        players: list[dict] -- active ESPN player records

    Returns:
        list[dict] -- teams with normalized assets and total received value
    """
    replacements = replacement_points(players)
    parsed_teams = []
    for team_name, assets_text in teams.items():
        assets = []
        for raw_asset in assets_text.split(","):
            asset_text = raw_asset.strip()
            if not asset_text:
                continue
            pick = parse_pick(asset_text)
            if pick:
                year_text = f"{pick['year']} " if pick["year"] else ""
                label = f"{year_text}{pick['round']}{'st' if pick['round'] == 1 else 'nd' if pick['round'] == 2 else 'rd'} round ({pick['tier']}) pick"
                assets.append({"name": label, "kind": "Pick", "value": pick_value(pick, league_format), "detail": f"{league_format} pick value heuristic"})
                continue
            player = choose_player(asset_text, players)
            value = player_value(player, league_format, replacements)
            status = str(player.get("injury_status") or "ACTIVE").replace("_", " ").title()
            rank = player.get("rank_ecr")
            position = player.get("position_id", "?")
            if player.get("season_points") is not None and position in replacements:
                advantage = max(0.0, float(player["season_points"]) - replacements[position])
                detail = f"{position} ROS {float(player['season_points']):.1f} pts; {advantage:.1f} above replacement"
            else:
                detail = f"{position} rank {rank:.0f}" if rank is not None else str(position)
            if status.upper() != "ACTIVE":
                detail += f", {status}"
            assets.append({"name": player.get("player_name") or asset_text, "kind": "Player", "value": value, "detail": detail})
        if not assets:
            raise ValueError(f"{team_name} has no trade assets. Add at least one player or pick.")
        parsed_teams.append({"name": team_name.strip(), "assets": assets, "total": package_value(assets)})
    return parsed_teams

def trade_recommendation(teams: list[dict]) -> tuple[str, list[dict]]:
    """
    Score each team's incoming package and rate the value balance

    Args:
        teams: list[dict] -- normalized trade teams and their received assets

    Returns:
        tuple[str, list[dict]] -- overall fairness recommendation and scored teams
    """
    average = sum(team["total"] for team in teams) / len(teams)
    highest = max((team["total"] for team in teams), default=1.0) or 1.0
    for team in teams:
        team["score"] = 100.0 * team["total"] / highest
        team["difference"] = team["total"] - average
        team["difference_percent"] = 100.0 * team["difference"] / average if average else 0.0
    lowest = min((team["total"] for team in teams), default=0.0)
    highest = max((team["total"] for team in teams), default=0.0)
    largest_gap = 100.0 * (highest - lowest) / highest if highest else 0.0
    if largest_gap <= 10:
        recommendation = "Fair trade"
    elif largest_gap <= 25:
        recommendation = "Slightly uneven; consider negotiating"
    else:
        recommendation = "Unfair trade; the packages are significantly unbalanced"
    return recommendation, teams

def parse_team_arguments(values: list[str]) -> dict[str, str]:
    """
    Convert repeated team command-line arguments into a team asset mapping

    Args:
        values: list[str] -- arguments formatted as Team Name=asset, asset

    Returns:
        dict[str, str] -- team names mapped to received trade assets
    """
    teams = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Team argument must look like 'Team Name=Player, 2027 1st early': {value}")
        name, assets = value.split("=", 1)
        if not name.strip():
            raise ValueError("Each team needs a name before the equals sign.")
        teams[name.strip()] = assets.strip()
    return teams

def prompt_teams() -> dict[str, str]:
    """
    Prompt for each team's incoming trade assets

    Args:
        None -- this function takes no arguments

    Returns:
        dict[str, str] -- team names mapped to received trade assets
    """
    print("Enter each team's incoming assets as Team Name: player, player, 2027 1st early")
    print("Enter at least two teams. Leave the team name blank when finished.")
    teams = {}
    while True:
        line = input("Team and assets: ").strip()
        if not line:
            break
        if ":" not in line:
            print("Use the format Team Name: asset, asset", file=sys.stderr)
            continue
        name, assets = line.split(":", 1)
        if name.strip():
            teams[name.strip()] = assets.strip()
    return teams

def main(teams: dict[str, str] | None = None, scoring: str = "PPR", week: int | None = None, league_format: str = "standard") -> int:
    """
    Run the fantasy football trade analysis workflow

    Args:
        teams: dict[str, str] | None -- team names mapped to comma-separated incoming assets
        scoring: str -- scoring format PPR, standard, or half PPR
        week: int | None -- NFL week used for the current player ranking snapshot

    Returns:
        int -- process exit status
    """
    parser = argparse.ArgumentParser(description="Compare incoming fantasy football trade packages for two or more teams.")
    parser.add_argument("--team", action="append", help="Team assets in the form 'Team Name=player, 2027 1st early'; repeat for each team")
    parser.add_argument("--type", dest="scoring", help="PPR (default), standard, or half PPR")
    parser.add_argument("--week", type=int, help="NFL week for the current player ranking snapshot")
    parser.add_argument("--format", dest="league_format", choices=("standard", "dynasty"), type=str.casefold, help="League format: standard (default) or dynasty")
    args = parser.parse_args()
    league_format = args.league_format or league_format.casefold()
    if league_format not in {"standard", "dynasty"}:
        parser.error("League format must be standard or dynasty.")
    scoring_key = re.sub(r"\s+", " ", (args.scoring or scoring or "PPR").strip().upper())
    scoring = SCORING_OPTIONS.get(scoring_key)
    if not scoring:
        parser.error("Type must be PPR, standard, half PPR, 0.5 PPR, or .5 PPR.")
    try:
        selected_teams = parse_team_arguments(args.team) if args.team else teams
        if not selected_teams:
            selected_teams = prompt_teams()
        if len(selected_teams) < 2:
            parser.error("Enter incoming assets for at least two teams.")
        season = season_year()
        selected_week = args.week or week or get_week(season)
        if not 1 <= selected_week <= 18:
            parser.error("Week must be from 1 to 18.")
        player_pool = espn_fantasy_players(season, selected_week, scoring)
        result_teams = parse_team_assets(selected_teams, player_pool, league_format)
        recommendation, result_teams = trade_recommendation(result_teams)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"\nNFL {season} Week {selected_week} | {scoring} scoring | {league_format.title()} league values\n")
    for team in result_teams:
        print(f"{team['name']} | overall score {team['score']:.1f}/100 | package value {team['total']:.1f} | {team['difference_percent']:+.1f}% vs. equal share")
        for asset in team["assets"]:
            print(f"  {asset['kind']:5} {asset['name'][:36]:36} {asset['value']:6.1f}  {asset['detail']}")
    print(f"\nRecommendation: {recommendation}.")
    best = max(result_teams, key=lambda team: team["total"])
    lowest = min(result_teams, key=lambda team: team["total"])
    if best["total"] != lowest["total"]:
        if lowest["total"] > 0:
            advantage = 100.0 * (best["total"] - lowest["total"]) / lowest["total"]
            print(f"{best['name']} makes out {advantage:.1f}% better in this trade than {lowest['name']} based on estimated package value.")
        else:
            print(f"{best['name']} comes out ahead; {lowest['name']} receives no projected value above replacement in this format.")
    print("Player values use projected rest-of-season points above a replacement starter, with replacement levels approximated for a 12-team, one-quarterback league. If ESPN does not provide a season projection, the analyzer falls back to positional rank. Package totals apply diminishing returns to additional assets. Dynasty mode uses lower pick values calibrated to this same player-value scale; player values remain rest-of-season estimates because age and multi-year projection data are unavailable.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(
        # Each team's value lists the assets that team receives
        teams={
            "Team 1": "Bucky Irving", # Team 1 receives
            "Team 2": "Tyler Higbee, 2027 2nd early", # Team 2 receives
        },
        scoring="PPR",
        week=None,
        league_format="dynasty",
    ))
