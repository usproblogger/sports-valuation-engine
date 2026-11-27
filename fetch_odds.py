import os
import re
import json
import requests
from datetime import datetime, timezone

API_KEY = os.environ.get("ODDS_API_KEY")

SPORTS = [
    {"key": "americanfootball_nfl", "category": "football"},
    {"key": "basketball_nba", "category": "basketball"},
    {"key": "icehockey_nhl", "category": "hockey"},
]

POPULARITY_INDEX = {
    # NFL (32 Teams)
    "Dallas Cowboys": 96, "Kansas City Chiefs": 95, "San Francisco 49ers": 91,
    "Philadelphia Eagles": 90, "Pittsburgh Steelers": 89, "Green Bay Packers": 88,
    "New England Patriots": 86, "Buffalo Bills": 85, "Baltimore Ravens": 84,
    "Detroit Lions": 84, "Chicago Bears": 83, "New York Giants": 82,
    "Las Vegas Raiders": 82, "Miami Dolphins": 81, "Minnesota Vikings": 81,
    "New York Jets": 80, "Seattle Seahawks": 80, "Cincinnati Bengals": 79,
    "Denver Broncos": 78, "Los Angeles Rams": 77, "Houston Texans": 76,
    "Cleveland Browns": 75, "New Orleans Saints": 74, "Los Angeles Chargers": 73,
    "Tampa Bay Buccaneers": 72, "Atlanta Falcons": 70, "Washington Commanders": 70,
    "Indianapolis Colts": 66, "Arizona Cardinals": 63, "Carolina Panthers": 60,
    "Tennessee Titans": 59, "Jacksonville Jaguars": 56,

    # NBA (30 Teams)
    "Los Angeles Lakers": 97, "Golden State Warriors": 94, "Boston Celtics": 93,
    "New York Knicks": 90, "Chicago Bulls": 86, "Miami Heat": 84,
    "Philadelphia 76ers": 83, "Dallas Mavericks": 83, "Phoenix Suns": 81,
    "Milwaukee Bucks": 80, "Denver Nuggets": 79, "Brooklyn Nets": 77,
    "Los Angeles Clippers": 76, "Oklahoma City Thunder": 76, "San Antonio Spurs": 75,
    "Houston Rockets": 73, "Cleveland Cavaliers": 73, "Minnesota Timberwolves": 72,
    "Toronto Raptors": 71, "Sacramento Kings": 68, "Indiana Pacers": 67,
    "New Orleans Pelicans": 65, "Memphis Grizzlies": 65, "Atlanta Hawks": 64,
    "Orlando Magic": 63, "Portland Trail Blazers": 61, "Utah Jazz": 59,
    "Washington Wizards": 57, "Detroit Pistons": 56, "Charlotte Hornets": 55,

    # NHL (32 Teams)
    "Toronto Maple Leafs": 91, "New York Rangers": 88, "Chicago Blackhawks": 85,
    "Boston Bruins": 85, "Montreal Canadiens": 84, "Edmonton Oilers": 84,
    "Pittsburgh Penguins": 83, "Detroit Red Wings": 81, "Colorado Avalanche": 80,
    "Vegas Golden Knights": 80, "Washington Capitals": 79, "Tampa Bay Lightning": 78,
    "Philadelphia Flyers": 76, "Los Angeles Kings": 75, "Vancouver Canucks": 74,
    "Dallas Stars": 73, "New Jersey Devils": 72, "Florida Panthers": 72,
    "Minnesota Wild": 70, "St. Louis Blues": 69, "Carolina Hurricanes": 69,
    "New York Islanders": 68, "Calgary Flames": 67, "Nashville Predators": 66,
    "Buffalo Sabres": 65, "Seattle Kraken": 65, "Winnipeg Jets": 64,
    "Ottawa Senators": 62, "Anaheim Ducks": 60, "San Jose Sharks": 58,
    "Utah Hockey Club": 57, "Columbus Blue Jackets": 54
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

def parse_spread_point_from_str(spread_str):
    if not spread_str or spread_str == "-":
        return None
    m = re.search(r"([+-]?\d+(?:\.\d+)?)", str(spread_str))
    return float(m.group(1)) if m else None

def grade_ats_result(rec, home_pts, away_pts):
    picked = rec.get("openingFavTeam")
    home = rec.get("homeTeam")
    away = rec.get("awayTeam")
    sp_point = rec.get("openingSpreadPoint")
    if sp_point is None:
        sp_point = parse_spread_point_from_str(rec.get("openingSpread"))
    if sp_point is None or picked not in (home, away):
        return None, None

    sp_price = rec.get("openingSpreadPrice")
    if sp_price is None:
        sp_price = -110

    fav_pts = home_pts if picked == home else away_pts
    dog_pts = away_pts if picked == home else home_pts
    adjusted_margin = (fav_pts + float(sp_point)) - dog_pts

    if abs(adjusted_margin) < 1e-9:
        return "PUSH", 0.0
    if adjusted_margin > 0:
        return "WIN", calc_profit_100(sp_price)
    return "LOSS", -100.0

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
            spread_outcomes = {o["name"]: o for o in markets.get("spreads", [])}

            if home not in h2h or away not in h2h:
                continue

            home_ml, away_ml = h2h[home], h2h[away]
            fav_team, lead_ml = (home, home_ml) if home_ml < away_ml else (away, away_ml)

            fav_sp_obj = spread_outcomes.get(fav_team, {})
            fav_point = fav_sp_obj.get("point")
            fav_sp_price = fav_sp_obj.get("price", -110)

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
                "spreadPoint": fav_point,
                "spreadPrice": fav_sp_price,
                "leadML": lead_ml,
                "gap": gap
            })

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
                    "openingSpreadPoint": fav_point,
                    "openingSpreadPrice": fav_sp_price,
                    "gap": gap,
                    "valueRating": val_rating,
                    "status": "PENDING",
                    "atsStatus": "PENDING",
                    "finalScore": None,
                    "profit100": None,
                    "atsProfit100": None
                }

            history[gid]["lastUpdatedUTC"] = now_iso
            history[gid]["latestFavTeam"] = fav_team
            history[gid]["latestLeadML"] = lead_ml
            history[gid]["latestSpread"] = spread_str
            history[gid]["latestSpreadPoint"] = fav_point
            history[gid]["latestSpreadPrice"] = fav_sp_price
            history[gid]["snapshots"] = history[gid].get("snapshots", 0) + 1

    # 2. CHECK COMPLETED SCORES ONCE DAILY (MORNING UTC RUN) TO GRADE ML & ATS OUTCOMES
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

                scores = {s["name"]: int(s["score"]) for s in g.get("scores", []) if s.get("score") is not None}
                home, away = history[gid]["homeTeam"], history[gid]["awayTeam"]
                if home not in scores or away not in scores:
                    continue

                home_pts, away_pts = scores[home], scores[away]
                picked = history[gid]["openingFavTeam"]
                ml = history[gid]["openingLeadML"]

                if history[gid].get("status") not in ("WIN", "LOSS"):
                    winner = home if home_pts > away_pts else (away if away_pts > home_pts else "TIE")
                    if winner == "TIE":
                        history[gid]["status"] = "PUSH"
                        history[gid]["profit100"] = 0.0
                    elif winner == picked:
                        history[gid]["status"] = "WIN"
                        history[gid]["profit100"] = calc_profit_100(ml)
                    else:
                        history[gid]["status"] = "LOSS"
                        history[gid]["profit100"] = -100.0

                if history[gid].get("atsStatus") not in ("WIN", "LOSS"):
                    ats_status, ats_profit = grade_ats_result(history[gid], home_pts, away_pts)
                    if ats_status:
                        history[gid]["atsStatus"] = ats_status
                        history[gid]["atsProfit100"] = ats_profit

                history[gid]["finalScore"] = f"{away} {away_pts} - {home} {home_pts}"
                history[gid]["gradedUTC"] = now_iso

    # 2B. BACKFILL ATS GRADES FOR ALREADY-COMPLETED GAMES IN HISTORY_LOG
    for gid, rec in history.items():
        if rec.get("finalScore") and rec.get("atsStatus") not in ("WIN", "LOSS", "PUSH"):
            m = re.match(r"^(.*?)\s+(\d+)\s+-\s+(.*?)\s+(\d+)$", rec["finalScore"])
            if m:
                away_pts, home_pts = int(m.group(2)), int(m.group(4))
                ats_status, ats_profit = grade_ats_result(rec, home_pts, away_pts)
                if ats_status:
                    rec["atsStatus"] = ats_status
                    rec["atsProfit100"] = ats_profit

    # 3. COMPUTE RUNNING BACKTEST SUMMARY (ML + ATS)
    graded = [v for v in history.values() if v.get("status") in ("WIN", "LOSS")]
    wins = sum(1 for v in graded if v.get("status") == "WIN")
    losses = sum(1 for v in graded if v.get("status") == "LOSS")
    net_profit = round(sum(v.get("profit100") or 0 for v in graded), 2)

    ats_graded = [v for v in history.values() if v.get("atsStatus") in ("WIN", "LOSS")]
    ats_wins = sum(1 for v in ats_graded if v.get("atsStatus") == "WIN")
    ats_losses = sum(1 for v in ats_graded if v.get("atsStatus") == "LOSS")
    ats_net_profit = round(sum(v.get("atsProfit100") or 0 for v in ats_graded), 2)

    high_val = [v for v in graded if v.get("valueRating", 0) >= 25]
    high_val_profit = round(sum(v.get("profit100") or 0 for v in high_val), 2)

    summary = {
        "lastSyncUTC": now_iso,
        "totalMemorizedGames": len(history),
        "totalGradedGames": len(graded),
        "record": f"{wins}W - {losses}L",
        "winRatePct": round((wins / len(graded)) * 100, 1) if graded else 0.0,
        "flat100NetProfit": net_profit,
        "atsGradedGames": len(ats_graded),
        "atsRecord": f"{ats_wins}W - {ats_losses}L",
        "atsWinRatePct": round((ats_wins / len(ats_graded)) * 100, 1) if ats_graded else 0.0,
        "atsFlat100NetProfit": ats_net_profit,
        "highValue25PlusCount": len(high_val),
        "highValue25PlusProfit": high_val_profit
    }

    save_json("odds_data.json", live_board)
    save_json("history_log.json", history)
    save_json("backtest_summary.json", summary)
    print(f"Synced {len(live_board)} active | Memorized {len(history)} total | ML Graded {len(graded)} | ATS Graded {len(ats_graded)}")

if __name__ == "__main__":
    run_pipeline()
