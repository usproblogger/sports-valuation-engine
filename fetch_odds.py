import os
import json
import requests
from datetime import datetime, timezone

API_KEY = os.environ.get("ODDS_API_KEY")

# 3 sports * 2 markets (h2h, spreads) * 2 runs/day * 30 days = 360 credits
# + 3 sports * 1 score check/day * 30 days = 90 credits -> 450 credits/month (under 500 free limit)
SPORTS = [
    {"key": "americanfootball_nfl", "category": "football"},
    {"key": "basketball_nba", "category": "basketball"},
    {"key": "icehockey_nhl", "category": "hockey"},
]

POPULARITY_INDEX = {
    "Dallas Cowboys": 95, "Kansas City Chiefs": 94, "Baltimore Ravens": 82,
    "New York Jets": 78, "Indianapolis Colts": 60, "Jacksonville Jaguars": 52,
    "Los Angeles Lakers": 96, "Boston Celtics": 92, "Golden State Warriors": 93,
    "Denver Nuggets": 76, "Oklahoma City Thunder": 74, "Memphis Grizzlies": 65,
    "Toronto Raptors": 68, "Sacramento Kings": 64, "Charlotte Hornets": 54,
    "Houston Rockets": 67, "Chicago Blackhawks": 80, "Toronto Maple Leafs": 88,
    "Edmonton Oilers": 84, "Vegas Golden Knights": 79, "Detroit Red Wings": 77,
    "San Jose Sharks": 55, "Columbus Blue Jackets": 50, "Ottawa Senators": 58,
    "Minnesota Vikings": 81, "San Francisco 49ers": 91, "Seattle Seahawks": 83
}

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_popularity_gap(home_team, away_team):
    return abs(POPULARITY_INDEX.get(home_team, 60) - POPULARITY_INDEX.get(away_team, 60))

def format_ml(price):
    return f"+{price}" if price > 0 else str(price)

def abbreviate(team_name):
    parts = team_name.split()
    return parts[-1][:3].upper() if parts else "FAV"

def calc_profit_100(ml):
    if ml > 0:
        return round(100.0 * (ml / 100.0), 2)
    if ml < 0:
        return round(100.0 * (100.0 / abs(ml)), 2)
    return 0.0

def get_win_prob(ml):
    if ml < 0:
        return abs(ml) / (abs(ml) + 100.0)
    if ml > 0:
        return 100.0 / (ml + 100.0)
    return 0.50

def run_pipeline():
    if not API_KEY:
        raise ValueError("Missing ODDS_API_KEY environment variable.")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    history = load_json("history_log.json", {})
    live_board = []

    # 1. FETCH CURRENT ODDS & MEMORIZE INTO HISTORY_LOG
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
            print(f"Odds skip {sport['key']}: HTTP {resp.status_code}")
            continue

        for game in resp.json():
            gid = game.get("id")
            home = game.get("home_team")
            away = game.get("away_team")
            commence_str = game.get("commence_time")
            commence_dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))

            bookmakers = game.get("bookmakers", [])
            if not bookmakers:
                continue

            markets = {m["key"]: m["outcomes"] for m in bookmakers[0].get("markets", [])}
            h2h = {o["name"]: o["price"] for o in markets.get("h2h", [])}
            spreads = {o["name"]: o.get("point") for o in markets.get("spreads", [])}

            if home not in h2h or away not in h2h:
                continue

            home_ml, away_ml = h2h[home], h2h[away]
            fav_team, lead_ml = (home, home_ml) if home_ml < away_ml else (away, away_ml)
            fav_point = spreads.get(fav_team)
            spread_str = f"{abbreviate(fav_team)} {'+' + str(fav_point) if fav_point > 0 else fav_point}" if fav_point is not None else "-"
            gap = get_popularity_gap(home, away)
            val_rating = round(gap * get_win_prob(lead_ml), 1)

            is_live = commence_dt <= now
            timeframe = "live" if is_live else "weekly"
            prefix = "🔴 LIVE | " if is_live else ""

            live_board.append({
                "id": gid,
                "timeframe": timeframe,
                "sport": sport["category"],
                "commenceTime": commence_str,
                "awayTeam": away,
                "awayML": away_ml,
                "homeTeam": home,
                "homeML": home_ml,
                "matchFormatted": f"{prefix}{away} ({format_ml(away_ml)}) @ {home} ({format_ml(home_ml)})",
                "spread": spread_str,
                "leadML": lead_ml,
                "gap": gap
            })

            # Memorize opening line & track latest pre-game/live snapshot
            if gid not in history:
                history[gid] = {
                    "id": gid,
                    "sport": sport["category"],
                    "sportKey": sport["key"],
                    "commenceTime": commence_str,
                    "awayTeam": away,
                    "homeTeam": home,
                    "firstSeenUTC": now_iso,
                    "openingFavTeam": fav_team,
                    "openingLeadML": lead_ml,
                    "openingSpread": spread_str,
                    "gap": gap,
                    "valueRating": val_rating,
                    "status": "PENDING",
                    "finalScore": None,
                    "profit100": None
                }

            history[gid]["lastUpdatedUTC"] = now_iso
            history[gid]["latestFavTeam"] = fav_team
            history[gid]["latestLeadML"] = lead_ml
            history[gid]["latestSpread"] = spread_str
            history[gid]["snapshots"] = history[gid].get("snapshots", 0) + 1

    # 2. CHECK COMPLETED SCORES ONCE DAILY (MORNING UTC RUN) TO GRADE OUTCOMES
    if now.hour < 14:
        for sport in SPORTS:
            score_url = f"https://api.the-odds-api.com/v4/sports/{sport['key']}/scores/"
            s_resp = requests.get(score_url, params={"apiKey": API_KEY, "daysFrom": 2}, timeout=15)
            if s_resp.status_code != 200:
                continue

            for g in s_resp.json():
                gid = g.get("id")
                if not g.get("completed") or gid not in history:
                    continue
                if history[gid]["status"] in ("WIN", "LOSS"):
                    continue

                scores = {s["name"]: int(s["score"]) for s in g.get("scores", []) if s.get("score") is not None}
                home, away = history[gid]["homeTeam"], history[gid]["awayTeam"]
                if home not in scores or away not in scores:
                    continue

                home_pts, away_pts = scores[home], scores[away]
                winner = home if home_pts > away_pts else (away if away_pts > home_pts else "TIE")
                picked = history[gid]["openingFavTeam"]
                ml = history[gid]["openingLeadML"]

                if winner == "TIE":
                    history[gid]["status"] = "PUSH"
                    history[gid]["profit100"] = 0.0
                elif winner == picked:
                    history[gid]["status"] = "WIN"
                    history[gid]["profit100"] = calc_profit_100(ml)
                else:
                    history[gid]["status"] = "LOSS"
                    history[gid]["profit100"] = -100.0

                history[gid]["finalScore"] = f"{away} {away_pts} - {home} {home_pts}"
                history[gid]["gradedUTC"] = now_iso

    # 3. COMPUTE RUNNING BACKTEST SUMMARY
    graded = [v for v in history.values() if v["status"] in ("WIN", "LOSS")]
    wins = sum(1 for v in graded if v["status"] == "WIN")
    losses = sum(1 for v in graded if v["status"] == "LOSS")
    net_profit = round(sum(v["profit100"] for v in graded), 2)
    high_val = [v for v in graded if v.get("valueRating", 0) >= 25]
    high_val_profit = round(sum(v["profit100"] for v in high_val), 2)

    summary = {
        "lastSyncUTC": now_iso,
        "totalMemorizedGames": len(history),
        "totalGradedGames": len(graded),
        "record": f"{wins}W - {losses}L",
        "winRatePct": round((wins / len(graded)) * 100, 1) if graded else 0.0,
        "flat100NetProfit": net_profit,
        "highValue25PlusCount": len(high_val),
        "highValue25PlusProfit": high_val_profit
    }

    save_json("odds_data.json", live_board)
    save_json("history_log.json", history)
    save_json("backtest_summary.json", summary)
    print(f"Synced {len(live_board)} active | Memorized {len(history)} total | Graded {len(graded)}")

if __name__ == "__main__":
    run_pipeline()
