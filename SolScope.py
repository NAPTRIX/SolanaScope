import requests
import csv
import json
from textblob import TextBlob
from prettytable import PrettyTable
import logging
import time
import random
import argparse
import webbrowser
from flask import Flask, render_template_string, jsonify, send_file, request
from io import StringIO
from typing import List, Dict, Optional

# CONFIG
COINGECKO_API = "https://api.coingecko.com/api/v3"
CATEGORIES = ["solana-meme-coins", "artificial-intelligence", "decentralized-finance-defi", "layer-1", "initial-coin-offerings"]
DEFAULT_CATEGORY = "artificial-intelligence"  # Default to AI coins
MIN_VOLUME = 500_000  # USD
MIN_PRICE = 0.0001  # Min price
MIN_CHANGE = 0.0  # Min 24h % change
MAX_SUPPLY_RATIO = 0.8  # Max circulating/total supply ratio
DEFAULT_SCORE_THRESHOLD = 5.0  # For hot picks
MAX_RESULTS = 10
REQUEST_DELAY = 0.2  # CoinGecko rate limit politeness
DEFAULT_FLASK_PORT = 5000  # Web server port

# logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)
app.config['results'] = []
app.config['category'] = DEFAULT_CATEGORY

# COIN DATA (CATEGORY FETCH)
def fetch_top_coins(category: str, per_page: int = 50) -> List[Dict]:
    """Fetch top coins from CoinGecko category"""
    url = f"{COINGECKO_API}/coins/markets"
    params = {
        "vs_currency": "usd",
        "category": category,
        "order": "market_cap_desc",
        "per_page": per_page,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "24h",
        "locale": "en"
    }
    
    for attempt in range(3):
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            coins = response.json()
            logger.info("Fetched %d coins from %s category", len(coins), category)
            time.sleep(REQUEST_DELAY)
            return coins
        except requests.RequestException as e:
            logger.error("Attempt %d: Error fetching coins for %s: %s", attempt + 1, category, e)
            time.sleep(2 ** attempt)
    logger.error("Failed to fetch coins for %s after retries", category)
    logger.info("Try valid categories: %s", ", ".join(CATEGORIES))
    return []

# Mock sentiment, optional
def mock_sentiment() -> float:
    """Mock sentiment score (0.1-0.5 for positive meme hype)"""
    return round(random.uniform(0.1, 0.5), 2)

# scoring
def score_investment(coin_data: Dict, sentiment_score: float = None, category_size: int = 1) -> float:
    """Score based on volume, 24h change, supply ratio, and optional sentiment"""
    score = 0.0
    
    volume = coin_data.get("total_volume", 0)
    if volume > MIN_VOLUME:
        score += min(5.0, volume / (100_000_000 / max(1, category_size / 50)))
    
    change_24h = coin_data.get("price_change_percentage_24h", 0)
    if change_24h > MIN_CHANGE:
        score += min(change_24h / 10, 3.0)
    
    circulating = coin_data.get("circulating_supply", 0)
    total = coin_data.get("total_supply", float("inf"))
    if total > 0 and circulating > 0:
        supply_ratio = circulating / total
        if supply_ratio < MAX_SUPPLY_RATIO:
            score += (1 - supply_ratio) * 2.0
    
    if sentiment_score:
        score += sentiment_score * 2.0
    
    return round(score, 2)

# dashboard
def build_terminal_dashboard(results: List[Dict], category: str, score_threshold: float) -> None:
    """Display ranked results in terminal"""
    if not results:
        print("No coins meet criteria.")
        return
    
    table = PrettyTable()
    table.field_names = [
        "Rank", "Coin", "Price ($)", "24h Change (%)", "Volume ($)", "Mkt Cap ($)", "Score"
    ]
    
    for i, result in enumerate(results, 1):
        table.add_row([
            i,
            result["name"],
            f"{result['price']:.6f}".rstrip('0').rstrip('.'),
            f"{result['change_24h']:.2f}%",
            f"{result['volume']:,}",
            f"{result['mkt_cap']:,}",
            result["score"]
        ])
    
    print(f"\nTop {len(results)} {category.replace('-', ' ').title()} Gems Dashboard")
    print(table)
    
    high_scores = [r for r in results if r["score"] > score_threshold]
    if high_scores:
        print(f"\n Hot Picks (Score >{score_threshold}): {[r['name'] for r in high_scores]}")

# CSV EXPORT 
def export_to_csv(results: List[Dict], filename: str = "crypto_gems.csv") -> None:
    """Export results to CSV"""
    if not results:
        logger.info("No results to export.")
        return
    
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Rank", "Coin", "Price ($)", "24h Change (%)", "Volume ($)", "Market Cap ($)", "Score"
        ])
        writer.writeheader()
        for i, result in enumerate(results, 1):
            writer.writerow({
                "Rank": i,
                "Coin": result["name"],
                "Price ($)": f"{result['price']:.6f}".rstrip('0').rstrip('.'),
                "24h Change (%)": f"{result['change_24h']:.2f}",
                "Volume ($)": result["volume"],
                "Market Cap ($)": result["mkt_cap"],
                "Score": result["score"]
            })
    logger.info("Exported results to %s", filename)

# web
def generate_web_dashboard(results: List[Dict], category: str, score_threshold: float) -> str:
    """Generate HTML for modern web dashboard with functional table"""
    # Map categories to chains for Dexscreener
    chain_map = {
        "solana-meme-coins": "solana",
        "artificial-intelligence": "ethereum",  # Approx for AI coins
        "decentralized-finance-defi": "ethereum",
        "layer-1": "ethereum",  # Approx for Layer 1
        "initial-coin-offerings": "ethereum"   # Approx for ICOs
    }
    chain = chain_map.get(category, "solana")  # Default to Solana if unmapped

    table_rows = ""
    for i, result in enumerate(results, 1):
        change_color = "var(--positive)" if result["change_24h"] > 0 else "var(--negative)"
        score_color = f"hsl({max(120 - result['score'] * 10, 0)}, 70%, 50%)"
        coin_name_safe = result["name"].replace(" ", "-").lower()
        dexscreener_url = f"https://dexscreener.com/search?q={coin_name_safe}"
        table_rows += (
            f'<tr><td>{i}</td><td><a href="{dexscreener_url}" target="_blank">{result["name"]}</a></td>'
            + f'<td>{result["price"]:.6f}'.rstrip('0').rstrip('.')
            + f'</td><td style="color:{change_color}">{result["change_24h"]:.2f}%</td><td>{result["volume"]:,}</td>'
            + f'<td>{result["mkt_cap"]:,}</td><td style="color:{score_color}" title="Score: Weighted sum of volume (0-5), 24h change (0-3), supply ratio (0-2), sentiment (0-2)">'
            + f'{result["score"]}</td></tr>'
        )
    
    high_scores = [r for r in results if r["score"] > score_threshold]
    hot_picks = f'<p class="hot-picks"><strong>🚀 Hot Picks (Score >{score_threshold}):</strong> {", ".join(r["name"] for r in high_scores)}</p>' if high_scores else ""
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{category.replace('-', ' ').title()} Gems Dashboard</title>
        <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg-light: #f4f4f9; --bg-dark: #1e1e1e;
                --text-light: #333; --text-dark: #ddd;
                --table-border-light: #ddd; --table-border-dark: #444;
                --button-bg-light: #4CAF50; --button-bg-dark: #2a6e2e;
                --button-hover-light: #45a049; --button-hover-dark: #1e5e22;
                --positive: #28a745; --negative: #dc3545;
            }}
            body {{ 
                font-family: 'Inter', sans-serif; 
                margin: 0; 
                padding: 20px; 
                transition: all 0.3s ease; 
            }}
            .light-mode {{ background: var(--bg-light); color: var(--text-light); }}
            .dark-mode {{ background: var(--bg-dark); color: var(--text-dark); }}
            h1 {{ text-align: center; font-weight: 700; margin-bottom: 20px; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .controls {{ 
                display: flex; 
                gap: 10px; 
                margin-bottom: 20px; 
                justify-content: center; 
                flex-wrap: wrap; 
            }}
            .hot-picks {{ text-align: center; font-size: 1.1em; margin-bottom: 20px; }}
            button {{ 
                padding: 10px 20px; 
                border: none; 
                border-radius: 8px; 
                cursor: pointer; 
                font-weight: 500; 
                transition: background 0.2s, transform 0.1s; 
            }}
            .light-mode button {{ background: var(--button-bg-light); color: white; }}
            .dark-mode button {{ background: var(--button-bg-dark); color: var(--text-dark); }}
            button:hover {{ 
                transform: translateY(-2px); 
            }}
            .light-mode button:hover {{ background: var(--button-hover-light); }}
            .dark-mode button:hover {{ background: var(--button-hover-dark); }}
            .score-filter, .search-bar {{ 
                display: flex; 
                align-items: center; 
                gap: 10px; 
            }}
            .score-filter input {{ width: 150px; }}
            .search-bar input {{ 
                padding: 8px; 
                border: 1px solid var(--table-border-light); 
                border-radius: 8px; 
                width: 200px; 
            }}
            .dark-mode .search-bar input {{ 
                border-color: var(--table-border-dark); 
                background: #2a2a2a; 
                color: var(--text-dark); 
            }}
            .score-filter span {{ font-weight: 500; }}
            table {{ 
                width: 100%; 
                border-collapse: collapse; 
                margin-bottom: 20px; 
                border: 1px solid var(--table-border-light); 
            }}
            .dark-mode table {{ border-color: var(--table-border-dark); }}
            th, td {{ 
                padding: 12px; 
                text-align: left; 
                border-bottom: 1px solid var(--table-border-light); 
            }}
            .dark-mode th, .dark-mode td {{ border-bottom: 1px solid var(--table-border-dark); }}
            th {{ 
                background: var(--button-bg-light); 
                color: white; 
                position: sticky; 
                top: 0; 
                z-index: 1; 
                cursor: pointer; 
            }}
            .dark-mode th {{ background: var(--button-bg-dark); }}
            th:hover {{ background: var(--button-hover-light); }}
            .dark-mode th:hover {{ background: var(--button-hover-dark); }}
            tr {{ 
                display: table-row; 
                background: #fff; 
            }}
            .dark-mode tr {{ background: #2e2e2e; }}
            tr:nth-child(even) {{ background: #f2f2f2; }}
            .dark-mode tr:nth-child(even) {{ background: #2a2a2a; }}
            tr:hover {{ background: #e0e0e0; }}
            .dark-mode tr:hover {{ background: #3a3a3a; }}
            .tooltip {{ position: relative; }}
            .tooltip .tooltiptext {{ 
                visibility: hidden; 
                width: 200px; 
                background: #555; 
                color: #fff; 
                text-align: center; 
                border-radius: 6px; 
                padding: 8px; 
                position: absolute; 
                z-index: 2; 
                bottom: 125%; 
                left: 50%; 
                margin-left: -100px; 
                opacity: 0; 
                transition: opacity 0.3s; 
            }}
            .dark-mode .tooltip .tooltiptext {{ background: #777; }}
            .tooltip:hover .tooltiptext {{ visibility: visible; opacity: 1; }}
            .loading {{ 
                display: none; 
                position: fixed; 
                top: 50%; 
                left: 50%; 
                transform: translate(-50%, -50%); 
                font-size: 1.2em; 
                color: var(--text-light); 
            }}
            .dark-mode .loading {{ color: var(--text-dark); }}
            @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
            @media (max-width: 768px) {{ 
                th, td {{ padding: 8px; }} 
                .controls {{ flex-direction: column; align-items: center; }} 
                .search-bar input {{ width: 150px; }} 
            }}
            @media (max-width: 480px) {{ 
                th, td {{ padding: 6px; }} 
                .search-bar input {{ width: 100px; }} 
            }}
        </style>
    </head>
    <body class="light-mode">
        <div class="container">
            <h1>Top {len(results)} {category.replace('-', ' ').title()} Gems Dashboard</h1>
            {hot_picks}
            <div class="controls">
                <button onclick="toggleTheme()">Toggle Dark Mode</button>
                <button onclick="refreshData()">Refresh Data</button>
                <button onclick="exportCSV()">Export CSV</button>
                <div class="score-filter">
                    <label for="scoreFilter">Filter by Score:</label>
                    <input type="range" id="scoreFilter" min="0" max="10" step="0.1" value="0" 
                           onchange="filterTable()">
                    <span id="scoreValue">0</span>
                </div>
                <div class="search-bar">
                    <label for="searchInput">Search Coins:</label>
                    <input type="text" id="searchInput" placeholder="Enter coin name..." 
                           onkeyup="searchTable()">
                </div>
            </div>
            <div class="loading" id="loading">Refreshing...</div>
            <table id="coinTable">
                <thead>
                    <tr>
                        <th class="tooltip" onclick="sortTable(0)">Rank<span class="tooltiptext">Position based on score</span></th>
                        <th class="tooltip" onclick="sortTable(1)">Coin<span class="tooltiptext">Name of the cryptocurrency</span></th>
                        <th class="tooltip" onclick="sortTable(2)">Price ($)<span class="tooltiptext">Current price in USD</span></th>
                        <th class="tooltip" onclick="sortTable(3)">24h Change (%)<span class="tooltiptext">Price change in last 24 hours</span></th>
                        <th class="tooltip" onclick="sortTable(4)">Volume ($)<span class="tooltiptext">24h trading volume in USD</span></th>
                        <th class="tooltip" onclick="sortTable(5)">Mkt Cap ($)<span class="tooltiptext">Market capitalization in USD</span></th>
                        <th class="tooltip" onclick="sortTable(6)">Score<span class="tooltiptext">Weighted sum: Volume (0-5), 24h Change (0-3), Supply Ratio (0-2), Sentiment (0-2)</span></th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
        <script>
            function sortTable(n) {{
                let table = document.getElementById('coinTable');
                let rows, switching = true, i, shouldSwitch, dir = 'asc', switchcount = 0;
                while (switching) {{
                    switching = false;
                    rows = table.getElementsByTagName('tr');
                    for (i = 1; i < (rows.length - 1); i++) {{
                        shouldSwitch = false;
                        let x = rows[i].getElementsByTagName('td')[n];
                        let y = rows[i + 1].getElementsByTagName('td')[n];
                        let xVal = isNaN(parseFloat(x.textContent)) ? x.textContent.toLowerCase() : parseFloat(x.textContent);
                        let yVal = isNaN(parseFloat(y.textContent)) ? y.textContent.toLowerCase() : parseFloat(y.textContent);
                        if (dir === 'asc' && xVal > yVal) {{
                            shouldSwitch = true;
                            break;
                        }} else if (dir === 'desc' && xVal < yVal) {{
                            shouldSwitch = true;
                            break;
                        }}
                    }}
                    if (shouldSwitch) {{
                        rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                        switching = true;
                        switchcount++;
                    }} else if (switchcount === 0 && dir === 'asc') {{
                        dir = 'desc';
                        switching = true;
                    }}
                }}
            }}
            function refreshData() {{
                document.getElementById('loading').style.display = 'block';
                $.get('/refresh', function(data) {{
                    window.location.reload();
                }}).fail(function() {{
                    document.getElementById('loading').style.display = 'none';
                    alert('Failed to refresh data. Please try again.');
                }});
            }}
            function toggleTheme() {{
                document.body.classList.toggle('dark-mode');
                document.body.classList.toggle('light-mode');
                localStorage.setItem('theme', document.body.classList.contains('dark-mode') ? 'dark' : 'light');
            }}
            function filterTable() {{
                let score = parseFloat(document.getElementById('scoreFilter').value);
                document.getElementById('scoreValue').textContent = score.toFixed(1);
                let table = document.getElementById('coinTable');
                let rows = table.getElementsByTagName('tr');
                let search = document.getElementById('searchInput').value.toLowerCase();
                for (let i = 1; i < rows.length; i++) {{
                    let scoreCell = rows[i].getElementsByTagName('td')[6];
                    let nameCell = rows[i].getElementsByTagName('td')[1];
                    let rowScore = parseFloat(scoreCell.textContent);
                    let rowName = nameCell.textContent.toLowerCase();
                    rows[i].style.display = (rowScore >= score && rowName.includes(search)) ? '' : 'none';
                }}
            }}
            function searchTable() {{
                filterTable();
            }}
            function exportCSV() {{
                window.location.href = '/export-csv';
            }}
            // Load saved theme
            if (localStorage.getItem('theme') === 'dark') {{
                document.body.classList.remove('light-mode');
                document.body.classList.add('dark-mode');
            }}
        </script>
    </body>
    </html>
    """
    return html_template

@app.route('/')
def dashboard():
    """Serve the web dashboard"""
    return render_template_string(generate_web_dashboard(
        app.config['results'], 
        app.config['category'], 
        app.config['score_threshold']
    ))

@app.route('/refresh')
def refresh():
    """Refresh data and update dashboard"""
    coins = fetch_top_coins(app.config['category'])
    if not coins:
        for fallback in [c for c in CATEGORIES if c != app.config['category']]:
            coins = fetch_top_coins(fallback)
            if coins:
                app.config['category'] = fallback
                break
        if not coins:
            return jsonify({"error": "All categories failed"}), 500
    
    candidates = []
    for coin in coins:
        if coin.get("current_price", 0) < MIN_PRICE:
            continue
        sentiment = mock_sentiment() if app.config['use_sentiment'] else None
        score = score_investment(coin, sentiment, category_size=len(coins))
        if score > 1.0 and coin["total_volume"] > MIN_VOLUME:
            candidates.append({
                "name": coin["name"],
                "price": coin["current_price"],
                "change_24h": coin["price_change_percentage_24h"],
                "volume": coin["total_volume"],
                "mkt_cap": coin["market_cap"],
                "score": score,
                "sentiment": sentiment
            })
        time.sleep(REQUEST_DELAY)
    
    app.config['results'] = sorted(candidates, key=lambda x: x["score"], reverse=True)[:MAX_RESULTS]
    return jsonify({"status": "success"})

@app.route('/export-csv')
def export_csv_web():
    """Export results as CSV download"""
    results = app.config['results']
    if not results:
        return jsonify({"error": "No results to export"}), 400
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "Rank", "Coin", "Price ($)", "24h Change (%)", "Volume ($)", "Market Cap ($)", "Score"
    ])
    writer.writeheader()
    for i, result in enumerate(results, 1):
        writer.writerow({
            "Rank": i,
            "Coin": result["name"],
            "Price ($)": f"{result['price']:.6f}".rstrip('0').rstrip('.'),
            "24h Change (%)": f"{result['change_24h']:.2f}",
            "Volume ($)": result["volume"],
            "Market Cap ($)": result["mkt_cap"],
            "Score": result["score"]
        })
    
    output.seek(0)
    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"{app.config['category']}_gems_{int(time.time())}.csv"
    )

# main
def main(category: str = DEFAULT_CATEGORY, export_csv: bool = False, 
         use_sentiment: bool = True, use_web: bool = True, 
         score_threshold: float = DEFAULT_SCORE_THRESHOLD, port: int = DEFAULT_FLASK_PORT):
    logger.info("Starting %s analysis (no X API needed)...", category)
    
    coins = fetch_top_coins(category)
    if not coins:
        logger.warning("Primary category %s failed. Trying fallbacks...", category)
        for fallback in [c for c in CATEGORIES if c != category]:
            coins = fetch_top_coins(fallback)
            if coins:
                logger.info("Switched to fallback category: %s", fallback)
                category = fallback
                break
        if not coins:
            logger.error("All categories failed. Exiting.")
            return
    
    candidates = []
    for coin in coins:
        if coin.get("current_price", 0) < MIN_PRICE:
            continue
        sentiment = mock_sentiment() if use_sentiment else None
        score = score_investment(coin, sentiment, category_size=len(coins))
        if score > 1.0 and coin["total_volume"] > MIN_VOLUME:
            candidates.append({
                "name": coin["name"],
                "price": coin["current_price"],
                "change_24h": coin["price_change_percentage_24h"],
                "volume": coin["total_volume"],
                "mkt_cap": coin["market_cap"],
                "score": score,
                "sentiment": sentiment
            })
        time.sleep(REQUEST_DELAY)
    
    ranked = sorted(candidates, key=lambda x: x["score"], reverse=True)[:MAX_RESULTS]
    if not ranked:
        logger.info("No investment candidates found meeting criteria.")
        return
    
    # Terminal output
    build_terminal_dashboard(ranked, category, score_threshold)
    
    # CSV export
    if export_csv:
        export_to_csv(ranked, f"{category}_gems_{int(time.time())}.csv")
    
    # Web dashboard
    if use_web:
        app.config['results'] = ranked
        app.config['category'] = category
        app.config['score_threshold'] = score_threshold
        app.config['use_sentiment'] = use_sentiment
        webbrowser.open(f"http://localhost:{port}")
        logger.info("Web dashboard running at http://localhost:%d (Ctrl+C to stop)", port)
        try:
            app.run(port=port, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            logger.info("Shutting down Flask server")
        except Exception as e:
            logger.error("Error running Flask server: %s", e)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Gem Analyzer")
    parser.add_argument("--category", choices=CATEGORIES, default=DEFAULT_CATEGORY, 
                       help="CoinGecko category to analyze")
    parser.add_argument("--export-csv", action="store_true", help="Export results to CSV")
    parser.add_argument("--no-sentiment", action="store_true", help="Disable mock sentiment")
    parser.add_argument("--no-web", action="store_true", help="Disable web interface")
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD,
                       help="Score threshold for hot picks")
    parser.add_argument("--port", type=int, default=DEFAULT_FLASK_PORT,
                       help="Port for web interface")
    args = parser.parse_args()
    main(args.category, args.export_csv, not args.no_sentiment, not args.no_web,
         args.score_threshold, args.port) 