#!/usr/bin/env python3
"""
Compare fantasy football starters using FantasyPros projections/rankings and ESPN matchups
Run from the repository root: python start_sit.py
"""

from __future__ import annotations
import argparse
import difflib
import html
import json
import re
import sys
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
FANTASYPROS_BASE = "https://www.fantasypros.com/nfl"
POSITIONS = {"WR": "WR", "TE": "TE", "RB": "RB", "QB": "QB", "FLEX": "FLX", "K": "K", "D": "DST", "DST": "DST", "HC": "HC"}
SCORING = {"PPR": "PPR", "STANDARD": "STD", "HALF PPR": "HALF", "0.5 PPR": "HALF", ".5 PPR": "HALF"}
POSITION_SLUGS = {"WR": "wr", "TE": "te", "RB": "rb", "QB": "qb", "K": "k", "DST": "dst"}
TEAM_CODES = {"ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS", "WSH"}

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

def get_text(url: str) -> str:
    """
    Fetch a web page as text

    Args:
        url: str -- page URL

    Returns:
        str -- decoded page content
    """
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; football-tools/1.0)"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not retrieve page {url}: {exc}") from exc

def parse_table_rows(page: str) -> list[list[dict[str, str]]]:
    """
    Extract table rows and cell markup from a web page

    Args:
        page: str -- HTML page content

    Returns:
        list[list[dict[str, str]]] -- table rows with raw and readable cell content
    """
    rows = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, flags=re.IGNORECASE | re.DOTALL)
        row = []
        for cell in cells:
            text = re.sub(r"<[^>]+>", " ", cell)
            text = re.sub(r"\s+", " ", html.unescape(text)).strip()
            row.append({"raw": cell, "text": text})
        if row:
            rows.append(row)
    return rows

def player_label(raw_html: str, cell_text: str) -> tuple[str, str, str]:
    """
    Read a player name, team, and position from a table cell

    Args:
        raw_html: str -- original player cell markup
        cell_text: str -- readable player cell content

    Returns:
        tuple[str, str, str] -- player name, NFL team abbreviation, and position
    """
    clean_text = re.sub(r"\s+", " ", cell_text.replace("Image:", " ")).strip()
    attrs = re.findall(r"\b(?:title|alt)\s*=\s*['\"]([^'\"]+)['\"]", raw_html, flags=re.IGNORECASE)
    candidates = [html.unescape(item).replace("Image:", "").strip() for item in attrs]
    name = next((item for item in candidates if len(item.split()) >= 2 and not re.search(r"\b[A-Z]\.", item)), "")
    tokens = clean_text.split()
    position = tokens[-1].upper() if tokens and tokens[-1].upper() in {"QB", "RB", "WR", "TE", "K", "DST", "HC"} else ""
    if position:
        tokens.pop()
    team = tokens[-1].upper() if tokens and tokens[-1].upper() in TEAM_CODES else ""
    if team:
        tokens.pop()
    if not name:
        name = " ".join(tokens)
        name = re.sub(r"^(?:[A-Z]\.\s+)+", "", name)
    return name.strip(), team, position

def fantasypros_page(kind: str, position: str, week: int, scoring: str) -> str:
    """
    Build a public FantasyPros page URL

    Args:
        kind: str -- page type named projections or rankings
        position: str -- fantasy position identifier
        week: int -- NFL week number
        scoring: str -- scoring format identifier

    Returns:
        str -- FantasyPros page URL
    """
    if kind == "rankings" and position == "FLX":
        path = f"{FANTASYPROS_BASE}/fantasy-football-rankings/weekly-flex.php"
    else:
        slug = POSITION_SLUGS.get(position)
        if not slug:
            raise RuntimeError(f"FantasyPros does not publish weekly {position} projections and rankings")
        section = "projections" if kind == "projections" else "rankings"
        path = f"{FANTASYPROS_BASE}/{section}/{slug}.php"
    params = {"week": week, "scoring": scoring}
    if kind == "rankings" and position != "FLX":
        params["type"] = "weekly"
    return f"{path}?{urlencode(params)}"

def fantasypros_players(kind: str, position: str, week: int, scoring: str) -> list[dict]:
    """
    Read weekly player projections or rankings from a public FantasyPros page

    Args:
        kind: str -- page type named projections or rankings
        position: str -- fantasy position identifier
        week: int -- NFL week number
        scoring: str -- scoring format identifier

    Returns:
        list[dict] -- normalized player projection or ranking records
    """
    positions = ["RB", "WR", "TE"] if kind == "projections" and position == "FLX" else [position]
    combined = []
    for item_position in positions:
        url = fantasypros_page(kind, item_position, week, scoring)
        page = get_text(url)
        for row in parse_table_rows(page):
            if kind == "projections":
                if len(row) < 3 or "player" in row[0]["text"].casefold():
                    continue
                name, team, row_position = player_label(row[0]["raw"], row[0]["text"])
                numbers = []
                for cell in row[1:]:
                    match = re.search(r"-?\d+(?:\.\d+)?", cell["text"].replace(",", ""))
                    numbers.append(float(match.group(0)) if match else None)
                if name and numbers and numbers[-1] is not None:
                    combined.append({"player_name": name, "team": team, "position_id": row_position or item_position, "points": numbers[-1]})
            else:
                if len(row) < 3:
                    continue
                try:
                    rank_match = re.search(r"\d+(?:\.\d+)?", row[0]["text"])
                    rank = float(rank_match.group(0)) if rank_match else None
                except ValueError:
                    rank = None
                name, team, row_position = player_label(row[1]["raw"], row[1]["text"])
                if name and rank is not None:
                    combined.append({"player_name": name, "team": team, "position_id": row_position, "rank_ecr": rank})
    if not combined:
        raise RuntimeError("No player rows were found on the FantasyPros pages; the site layout may have changed")
    return combined

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
        projections = fantasypros_players("projections", position, selected_week, scoring)
        rankings = fantasypros_players("rankings", position, selected_week, scoring)
        games = get_games(season, selected_week)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    matchups, team_totals = matchup_by_team(games)
    results = []
    for name in names:
        try:
            projection = choose_player(name, projections)
            rank = choose_player(name, rankings)
            points = get_projection_points(projection, scoring)
            if points is None:
                raise ValueError(f"No {scoring} projection was returned for {name}.")
            rank_num = rank.get("rank_ecr") or rank.get("rank_ave") or rank.get("rank")
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
    max_rank = max((x["rank"] or len(rankings) or 1 for x in results), default=1)
    for item in results:
        model_score = max(0.0, min(100.0, 100 * item["adjusted"] / max_points))
        rank_score = 100 * (1 - ((item["rank"] or max_rank) - 1) / max(max_rank, 1))
        item["score"] = 0.7 * model_score + 0.3 * rank_score
    results.sort(key=lambda x: x["score"], reverse=True)
    print(f"\nWeek {selected_week} | {season} | {scoring} scoring | Position: {pos_key}\n")
    print(f"{'Player':25} {'Pos':4} {'Opp':18} {'Proj':>7} {'Adj':>7} {'ECR':>6} {'Score':>7}")
    print("-" * 73)
    for x in results:
        rank = f"{x['rank']:.0f}" if x["rank"] is not None else "—"
        print(f"{x['name'][:25]:25} {x['position'][:4]:4} {x['matchup'][:18]:18} {x['points']:7.1f} {x['adjusted']:7.1f} {rank:>6} {x['score']:7.1f}")
    print(f"\nRecommendation: Start {results[0]['name']} (highest blended comparison score).")
    print("Score blends 70% relative FantasyPros projections (with a small ESPN odds-based team scoring adjustment) and 30% relative expert consensus rank; it is a comparison aid, not a guaranteed outcome.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(
        players="Rachaad White, JK Dobbins",
        position="Flex",
        week=7,
        scoring="PPR",
    ))
