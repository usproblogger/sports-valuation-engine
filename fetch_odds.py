import os
import json
import requests
from datetime import datetime, timezone

API_KEY = os.environ.get("ODDS_API_KEY")

# 4 sports * 2 markets (h2h, spreads) * 2 runs/day * 30 days = 480 credits/month (under 500 free limit)
SPORTS = [
    {"key": "americanfootball_nfl", "category": "football"},
    {"key": "basketball_nba", "category": "basketball"},
    {"key": "icehockey_nhl", "category": "hockey"},
    {"key": "soccer_uefa_champs_league", "category": "soccer"},
]

# Baseline popularity index (0-100) for major franchises to calculate Popularity Gap
POPULARITY_INDEX = {
    "Dallas Cowboys": 95, "Kansas City Chiefs": 94, "Baltimore Ravens": 82,
    "New York Jets": 78, "Indianapolis Colts": 60, "Jacksonville Jaguars": 52,
    "Los Angeles Lakers": 96, "Boston Celtics": 92, "Golden State Warriors": 93,
    "Denver Nuggets": 76, "Oklahoma City Thunder": 74, "Memphis Grizzlies": 65,
    "Toronto Raptors": 68, "Sacramento Kings": 64, "Charlotte Hornets": 54,
    "Houston Rockets": 67, "Chicago Blackhawks": 80, "Toronto Maple Leafs": 88,
    "Edmonton Oilers": 84, "Vegas Golden Knights": 79, "Detroit Red Wings": 77,
    "San Jose Sharks": 55, "Columbus Blue Jackets": 50, "Ottawa Senators": 58,
    "Real Madrid": 98, "Arsenal": 90, "Liverpool": 92,
    "Slavia Prague": 48, "AEK Athens": 50, "Fenerbahce": 66
}

def get_popularity_gap(home_team, away_team):
    home_score = POPULARITY_INDEX.get(home_team, 60)
    away_score = POPULARITY_INDEX.get(away_team, 60)
    return abs(home_score - away_score)

def format_ml(price):
    return f"+{price}" if price > 0 else str(price)

def abbreviate(team_name):
    parts = team_name.split()
    return parts[-1][:3].upper() if parts else "FAV"

def fetch_all_odds():
    if not API_KEY:
        raise ValueError("Missing ODDS_API_KEY environment variable.")

    output = []
    now = datetime.now(timezone.utc)

    for sport in SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport['key']}/odds/"
        params = {
            "apiKey": API_KEY,
            "regions": "us",
            "markets": "h2h,spreads",
            "oddsFormat": "american",
            "bookmakers": "draftkings,fanduel,betmgm"
        }

        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"Skipping {sport['key']}: HTTP {resp.status_code}")
            continue

        games = resp.json()
        for game in games:
            home = game.get("home_team")
            away = game.get("away_team")
            commence_str = game.get("commence_time")
            commence_dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))

            is_live = commence_dt <= now
            timeframe = "live" if is_live else "weekly"
            prefix = "🔴 LIVE | " if is_live else ""

            bookmakers = game.get("bookmakers", [])
            if not bookmakers:
                continue

            markets = {m["key"]: m["outcomes"] for m in bookmakers[0].get("markets", [])}
            h2h_outcomes = {o["name"]: o["price"] for o in markets.get("h2h", [])}
            spread_outcomes = {o["name"]: o.get("point") for o in markets.get("spreads", [])}

            if home not in h2h_outcomes or away not in h2h_outcomes:
                continue

            home_ml = h2h_outcomes[home]
            away_ml = h2h_outcomes[away]

            if home_ml < away_ml:
                fav_team, lead_ml = home, home_ml
            else:
                fav_team, lead_ml = away, away_ml

            fav_point = spread_outcomes.get(fav_team)
            if fav_point is not None:
                point_str = f"+{fav_point}" if fav_point > 0 else str(fav_point)
                spread_str = f"{abbreviate(fav_team)} {point_str}"
            else:
                spread_str = "-"

            match_formatted = f"{prefix}{away} ({format_ml(away_ml)}) @ {home} ({format_ml(home_ml)})"
            gap = get_popularity_gap(home, away)

            output.append({
                "timeframe": timeframe,
                "sport": sport["category"],
                "matchFormatted": match_formatted,
                "spread": spread_str,
                "leadML": lead_ml,
                "gap": gap
            })

    with open("odds_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Saved {len(output)} games to odds_data.json")

if __name__ == "__main__":
    fetch_all_odds()
