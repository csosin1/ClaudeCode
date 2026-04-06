# Gym Intelligence — Basic-Fit Competitive Tracker

A Python tool that tracks the competitive gym landscape across Basic-Fit's core European markets (Netherlands, Belgium, France, Spain, Luxembourg, Germany) using OpenStreetMap data, AI-powered chain classification, and quarterly competitive analysis.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize the database
python db.py

# Set your Anthropic API key (required for classification and analysis)
export ANTHROPIC_API_KEY=your-key-here
```

## Usage

### First Run — Collect Data

```bash
# Collect gym locations from OpenStreetMap (takes 10-30 minutes)
python collect.py

# Classify chains using Claude (requires ANTHROPIC_API_KEY)
python classify.py

# Generate quarterly analysis
python analyze.py
```

### Or run the full pipeline at once

```bash
python scheduler.py --now
```

### Launch the Web UI

```bash
streamlit run app.py
```

The app will be available at `http://localhost:8501`.

### Scheduled Runs

```bash
# Start the scheduler (runs on first Monday of each quarter)
python scheduler.py
```

## Architecture

| File | Purpose |
|------|---------|
| `db.py` | Database schema, connection helpers, shared utilities |
| `collect.py` | OSM Overpass API data collection, chain name normalization |
| `classify.py` | AI-powered chain classification via Claude API |
| `analyze.py` | Quarterly competitive analysis report generation |
| `app.py` | Streamlit web UI (4 pages) |
| `scheduler.py` | APScheduler-based quarterly pipeline runner |

## Data Sources

- **OpenStreetMap** via Overpass API — gym locations, brands, addresses
- **Claude API** (claude-sonnet-4-20250514) — chain classification and competitive analysis
- **Chain websites** — pricing data extraction for large chains

## Web UI Pages

1. **Market Overview** — market share charts, chain comparison cards
2. **Chain Explorer** — individual chain profiles, location maps, growth trends
3. **Competitive Analysis** — AI-generated quarterly reports
4. **Admin / Refresh** — run pipeline, manually review chains, export data
