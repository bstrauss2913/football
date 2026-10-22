#!/usr/bin/env python3
"""
Compare prospective fantasy football picks using ESPN projections and rankings
Run from the repository root: python draft_analyzer.py
"""

from __future__ import annotations

import argparse
import sys
from start_sit import SCORING, choose_player, espn_fantasy_players, get_week, season_year

def parse_names(value: str) -> list[str]:
    """
    Split comma-separated player names

    Args:
          value: str -- comma-separated player names

    Returns:
          list[str] -- player names with surrounding whitespace removed
    """
    return [name.strip() for name in value.split(",") if name.strip()]

def calculate_scores(players: list[dict], all_players: list[dict]) -> list[dict]:
    """
    Calculate comparative draft scores for matched players

    Args:
          players: list[dict] -- matched player records to compare
          all_players: list[dict] -- ESPN player records used to normalize positional ranks

    Returns:
          list[dict] -- player records with comparative scores
    """
    max_points = max((float(row.get("points") or 0) for row in players), default=0) or 1
    rank_limits = {
        position: max((float(row["rank_ecr"]) for row in all_players if row.get("position_id") == position and row.get("rank_ecr")), default=1)
        for position in {str(row.get("position_id") or "") for row in all_players}
    }
    results = []
    for player in players:
        points = float(player.get("points") or 0)
        position = str(player.get("position_id") or "")
        try:
            rank = float(player.get("rank_ecr"))
        except (TypeError, ValueError):
            rank = rank_limits.get(position, 1)
        max_rank = rank_limits.get(position, 1)
        projection_score = 100 * points / max_points
        rank_score = max(0.0, min(100.0, 100 * (1 - (rank - 1) / max(max_rank - 1, 1))))
        results.append({**player, "score": 0.7 * projection_score + 0.3 * rank_score, "rank": rank})
    return sorted(results, key=lambda row: row["score"], reverse=True)

def main(players: str | None = None, scoring: str | None = None, week: int | None = None) -> int:
    """
    Run the fantasy draft recommendation workflow

    Args:
          players: str | None -- comma-separated prospective player names
          scoring: str | None -- PPR, standard, or half PPR scoring format
          week: int | None -- NFL week used for current-season projections

    Returns:
          int -- process exit status
    """
    parser = argparse.ArgumentParser(description="Compare fantasy football draft candidates")
    parser.add_argument("--players", help="Comma-separated player names")
    parser.add_argument("--type", dest="scoring", help="PPR, standard, or half PPR")
    parser.add_argument("--week", type=int, help="NFL week used for current-season rankings; defaults to ESPN's current week")
    args = parser.parse_args()

    names = parse_names(args.players or players or input("Players to compare (comma-separated): "))
    if len(names) < 2:
        parser.error("Enter at least two player names to compare.")
    scoring_key = (args.scoring or scoring or "PPR").strip().upper().replace("0.5", "0.5")
    scoring_key = {"HALF PPR": "HALF PPR", ".5 PPR": ".5 PPR"}.get(scoring_key, scoring_key)
    scoring_id = SCORING.get(scoring_key)
    if scoring_id is None:
        parser.error("Scoring must be PPR, standard, half PPR, 0.5 PPR, or .5 PPR.")

    season = season_year()
    try:
        selected_week = args.week or week or get_week(season)
        if not 1 <= selected_week <= 18:
            parser.error("Week must be from 1 to 18.")
        player_data = espn_fantasy_players(season, selected_week, scoring_id)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    matched = []
    for name in names:
        try:
            matched.append(choose_player(name, player_data))
        except ValueError as exc:
            print(f"Warning: {exc}", file=sys.stderr)
    if not matched:
        print("No entered players could be matched to ESPN projections.", file=sys.stderr)
        return 1

    results = calculate_scores(matched, player_data)
    print(f"\n{season} NFL season | Week {selected_week} projections | {scoring_id} scoring\n")
    print(f"{'Player':27} {'Pos':5} {'Team':5} {'Proj pts':>9} {'Rank':>7} {'Draft score':>12}")
    print("-" * 70)
    for row in results:
        print(f"{row.get('player_name', '')[:27]:27} {row.get('position_id', '?')[:5]:5} {row.get('team', '')[:5]:5} {float(row.get('points') or 0):9.1f} {row['rank']:7.0f} {row['score']:12.1f}")
    print(f"\nRecommendation: Draft {results[0].get('player_name')} (highest blended score).")
    print("Score blends 70% relative projected points and 30% relative ESPN positional rank among available players; it is a comparison aid and does not account for roster needs or draft position.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(
        players="Chase Brown, Omarion Hampton",
        scoring="PPR",
        week=None,
    ))
