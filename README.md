# d2c-ai-platform

AI platform for D2C brands — unified data layer, chat with citations, autonomous agent.

**Status**: v0 working. All core components implemented and integrated. Ready for testing with demo data.

---

## The Problem

D2C founders run their business across 5+ SaaS tools. Answering one cross-tool question takes 30 minutes of Excel stitching. Most don't bother — they run on vibes.

We're building the intelligence layer that sits across all their tools: one place to ask questions, get cited answers, and receive autonomous recommendations.

---

## What We Built

A working v0 with five hard requirements:

1. **3 proper connectors** (Shopify, Razorpay, Meta Ads) behind one shared abstraction
2. **Universal data model** with provenance on every row
3. **Chat layer** with tool-use loop and citation discipline
4. **One autonomous agent** that watches data and proposes savings (no live actions)
5. **Scalability harness** built for 1 merchant, designed for 10,000

---

## Architecture — 5-Line Summary

```
Users → FastAPI REST API (async-native)
        ↓
     PostgreSQL (one universal metrics table, merchant_id on every row)
        ↓
     Celery workers (Full-Funnel Attribution Agent, separate scaling)
        ↓
React frontend (stateless chat + metrics dashboard)
```

No full microservices. Modular monolith for API layer, separate process for agent.
Fault isolation: agent crashes don't take down chat.
At 10k merchants, agent jobs are the biggest consumer — separate ASG scales independently.

---

## 1. Connectors: Which 3. Why These 3.

**The three**: Shopify, Razorpay, Meta Ads.

**Why**: Complete D2C funnel coverage (India-specific).
- **Shopify**: Core commerce — orders, products, revenue, returns. ✓ Orders = conversion signal.
- **Razorpay**: Payments and settlements (India-specific). ✓ Payments = revenue realization. Refunds = quality signal.
- **Meta Ads**: Ad spend, impressions, clicks, conversions. ✓ Spend = cost of acquisition.

**Pattern**: All three share one base class with `fetch()` and `normalize()` methods.
- `fetch(start_date, end_date)` — raw API responses
- `normalize(raw_data)` — universal schema
- Subclasses add nothing else. Swappable.

**Connector registry pattern**: @register decorator + lookup. Adding a 4th connector requires:
1. 3–5 enum values in `models/enums.py`
2. New `connectors/fourth.py` with `@register` decorator
3. One import line in `connectors/__init__.py`

**Zero changes to sync jobs or API routes.** The seam is sealed.

---

## 2. Schema: Why This Shape.

One table. All data. All connectors.

```
Metric (
  merchant_id: UUID,                  # Multi-tenancy
  source: str (shopify|razorpay|meta_ads),
  source_record_id: str,              # Original ID in source system
  metric_type: str,                   # ORDER_REVENUE, AD_SPEND, PAYMENT_CAPTURED, etc.
  value: Decimal(20, 4),              # High precision for money
  currency: str (ISO 4217) | NULL,    # INR, USD, etc.
  date: Date,                         # Business date, not transaction time
  
  dimensions: JSONB | NULL,           # Queryable breakdown axes
                                      # e.g. {"campaign_id": "123", "financial_status": "paid"}
                                      # GIN-indexed for fast JSONB queries
  
  raw_data: JSONB,                    # Full API response, provenance only
                                      # Product code NEVER reads this
  
  fetched_at: DateTime,               # When we pulled it from source
  created_at: DateTime,               # When row was inserted
)
```

**Unique constraint**: `(merchant_id, source, source_record_id, metric_type)` prevents duplicate ingestion.

**Indexes**:
- `(merchant_id, source, date)` — optimizes time-series queries (most common)
- GIN on `dimensions` — enables fast JSONB queries

**Why JSONB dimensions?**
- Avoids sparse nullable columns for connector-specific fields
- Supports drill-down: "show me revenue by campaign" or "show me refunds by reason"
- Not every connector has every dimension — SQL would be a nightmare
- Product code reaches into `dimensions`, never `raw_data` (bright line)

**Fan-out pattern**: One Shopify order → 6 metric rows:
- `ORDER_REVENUE`, `ORDER_COUNT`, `ORDER_TAX`, `ORDER_SHIPPING`, `ORDER_DISCOUNT`, `ORDER_REFUND`
- All share the same `source_record_id`
- Unique constraint prevents dups on re-sync

**Monetary metrics require currency**. Validator enforces this at the connector boundary (Pydantic `NormalizedMetric`). Bad data never reaches the database.

**Currency strategy**: Store source currency. Do FX conversion at query time (never bake stale rates into provenance).

---

## 3. Chat Layer: The Tool Schema. Citation Works.

Four tools. OpenAI function calling format.

```python
query_metrics_aggregate(
  merchant_id: UUID,
  metric_type: str (ORDER_REVENUE | AD_SPEND | ...),
  aggregation: str (SUM | AVG | COUNT | MIN | MAX),
  date_from: date, date_to: date,
  dimension_filter: dict | None  # e.g. {"campaign_id": "123"}
)
→ {
  "result": 5000.00,
  "cited_row_ids": [uuid1, uuid2, uuid3]  # Point user back to source rows
}

query_metrics_timeseries(
  merchant_id: UUID,
  metric_type: str,
  date_from: date, date_to: date
)
→ {
  "timeseries": [
    {"date": "2026-05-18", "value": 1000.00, "cited_row_ids": [uuid1, uuid2]},
    ...
  ]
}

query_metrics_breakdown(
  merchant_id: UUID,
  metric_type: str,
  group_by: str (dimension key),
  date_from: date, date_to: date
)
→ {
  "breakdown": [
    {"dimension_value": "campaign_123", "value": 3000.00, "cited_row_ids": [uuid1]},
    ...
  ]
}

calculate_roas(
  merchant_id: UUID,
  date_from: date, date_to: date,
  ad_spend_source: str (meta_ads),
  revenue_source: str (shopify)
)
→ {
  "roas": 3.42,
  "revenue": 5000.00, "cited_revenue_ids": [...],
  "ad_spend": 1460.00, "cited_spend_ids": [...]
}
```

**Citation contract**: Every numerical claim is backed by source row IDs.

LLM system prompt enforces citation discipline:
```
CRITICAL CITATION RULE:
Every numerical claim you make MUST include the metric row IDs that support it.
Format: "Total revenue was $5,000 [cited: row_id_1, row_id_2, ...]"
```

**How it works**:
1. User asks a question
2. LLM decides which tools to call
3. Tools return results + cited row IDs
4. LLM includes citations in final response
5. API validates all citations (row IDs exist, belong to merchant)

**Multi-tenancy**: Every tool filters by `merchant_id`. No cross-merchant data bleed.

---

## 4. Agent: What It Does. Why This One.

**Purpose**: Full-funnel attribution. Watch the complete conversion chain.

```
Meta Ads spend → Shopify orders → Razorpay settlements/refunds
```

**Three detection modes** (hardcoded thresholds, deterministic):

1. **`spend_without_conversion`**: High spend, low orders.
   - Condition: `ad_spend > ₹5,000 AND ROAS < 1.5`
   - Recommendation: Review creative, tighten audience

2. **`orders_without_settlement`**: High orders, low payment capture.
   - Condition: `(captured_payments / total_orders) < 0.85 AND orders >= 10`
   - Recommendation: Check Razorpay for failed payments

3. **`conversion_with_returns`**: High orders, high refunds.
   - Condition: `(refund_amount / order_revenue) > 0.20 AND orders >= 10`
   - Recommendation: Refine audience, review product description

4. **`healthy`**: All thresholds within bounds.
   - No recommendation needed.

**Hybrid approach**:
- **Thresholds** (hardcoded): Deterministic detection. Auditable, testable.
- **LLM** (reasoning only): Called ONLY when non-healthy mode detected. Generates recommendation + citations. Healthy = no LLM call = cost savings.

**Lookback window**: 7 days ending yesterday.
- Avoids incomplete same-day data
- Avoids settlement lag (Razorpay 1–2 days)
- Daily re-evaluation: late-arriving refunds change the picture

**Output**: Structured run log with:
- `detection_mode` (spend_without_conversion | orders_without_settlement | conversion_with_returns | healthy)
- `data_snapshot` (exact numbers analyzed)
- `reasoning` (LLM output, nullable for healthy)
- `recommendation` (LLM output, nullable for healthy)
- `confidence_score` (0.50–0.99, threshold-distance heuristic)
- `cited_metric_ids` (list of row IDs analyzed)
- `status` (completed | failed | skipped)

**Trigger**: Daily Celery beat job at 2 AM UTC (after settlement lag).

**Failure handling**: Missing connector data? Agent logs gap and skips merchant.

**No live actions**: Agent proposes, founder decides. Full transparency.

---

## 5. Scale: From 1 Merchant to 10,000. What Breaks. What We Built.

**At 1 merchant**: Works. Demo connectors seeded. Agent runs daily.

**At 100 merchants**:
- 3 sync jobs/day × 100 = 300 API calls. Still fine.
- Chat queries are real-time. Database queries need indexes.
- Agent jobs run sequentially. Slow but works.

**Bottleneck 1: Sync jobs** (at ~1,000 merchants).
- **Problem**: 30,000 API calls per cycle. Blocking.
- **Solution**: Celery + SQS. Queue sync jobs. Workers pull from queue, scale independently.

**Bottleneck 2: Database connections** (at ~500 merchants).
- **Problem**: PostgreSQL default max 100 connections. Each API instance needs 10–20.
- **Solution**: PgBouncer connection pooling. 1 connection per API instance, pool to DB.
- **Next**: Read replicas for chat queries (queries ≠ writes).

**Bottleneck 3: LLM rate limits** (at ~2,000 merchants).
- **Problem**: OpenRouter has per-API-key limits. Agent + chat both call LLM. One merchant's spike blocks others.
- **Solution**: Per-tenant request queue. Backoff + retry. Fair sharing.

**What we've built to absorb scale**:
- Modular monolith: No service boundary overhead until we split.
- Async I/O: FastAPI + asyncpg = 100s of concurrent requests on 1 instance.
- Connectors are idempotent: Re-sync same date range = duplicate prevention via unique constraint.
- Agent is isolated: Separate Celery process, separate ASG. Crashes don't affect chat.
- Database constraints are tight: (merchant_id, source, source_record_id, metric_type) prevents bad re-ingestion.

---

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis (for Celery broker/backend)
- Node.js 18+ (frontend)

### Setup

**Backend**:
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

**Database**:
```bash
# Create PostgreSQL user and database
createuser -P d2c     # Enter password when prompted
createdb -O d2c d2c

# Set DATABASE_URL in .env
export DATABASE_URL="postgresql+asyncpg://d2c:password@localhost/d2c"

# Run migrations
alembic upgrade head

# Seed demo merchants + metrics
python seed.py
```

**Environment**:
```bash
cp .env.example .env
# Edit .env with your values:
# - DATABASE_URL (PostgreSQL connection)
# - OPENROUTER_API_KEY (or AZURE_OPENAI_KEY for prod)
# - CELERY_BROKER_URL (Redis)
# - CELERY_RESULT_BACKEND (Redis)
```

**Run API server**:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend**:
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5174/ and paste a demo merchant UUID from the seed output.

### Testing

**Without Celery** (for quick testing):
- Click "RUN AGENT →" button. It uses `?sync=true` parameter.
- Agent runs synchronously, returns results immediately.
- No Celery workers required.

**With Celery** (for production):
```bash
# Terminal 1: Start Celery worker
celery -A agent.tasks worker --loglevel=info

# Terminal 2: Start Celery beat (scheduler)
celery -A agent.scheduler beat --loglevel=info

# Then click "RUN AGENT →" without sync=true parameter
```

### Demo Merchants (Pre-seeded)

| Name | UUID | Detection Mode |
|---|---|---|
| Nykaa Fashions Demo | `a1a1a1a1-a1a1-4a1a-8a1a-a1a1a1a1a1a1` | healthy |
| QuickFashion Co. | `b2b2b2b2-b2b2-4b2b-8b2b-b2b2b2b2b2b2` | spend_without_conversion |
| ReturnKing Boutique | `c3c3c3c3-c3c3-4c3c-8c3c-c3c3c3c3c3c3` | conversion_with_returns |

Each merchant has 280 metric rows seeded (7 days × 3 connectors × ~13 metrics/day).

---

## API Endpoints

### Merchants
- `POST /merchants` — Create merchant
- `GET /merchants` — List merchants
- `GET /merchants/{id}` — Get single merchant
- `PATCH /merchants/{id}` — Update merchant
- `DELETE /merchants/{id}` — Soft delete

### Connectors
- `POST /merchants/{id}/connectors` — Register connector
- `GET /merchants/{id}/connectors` — List connectors
- `POST /merchants/{id}/connectors/demo/register` — Register demo connectors (for testing)
- `POST /merchants/{id}/connectors/{source}/sync` — Trigger sync
- `GET /merchants/{id}/connectors/{source}/status` — Sync status

### Chat
- `POST /chat` — Send message, get cited response

### Agent
- `GET /merchants/{id}/agent/logs` — List agent runs
- `GET /merchants/{id}/agent/logs/{log_id}` — Get single run
- `POST /merchants/{id}/agent/run` — Trigger agent run (add `?sync=true` for testing)

---

## Where It Breaks

**Chat layer** (at ~100k concurrent queries):
- Timeout on complex multi-tool chains
- LLM latency stalls user waiting for response
- **Fix**: Async background processing, WebSocket subscriptions

**Agent detection** (at ~5k merchants with real data):
- Hardcoded thresholds don't adapt to merchant cohort
- False positives on seasonal patterns (e.g., Diwali spike)
- **Fix**: Percentile-based thresholds (e.g., "worse than 90% of peers")

**Data freshness** (at ~10k merchants):
- Sync jobs run daily, but data is 24+ hours old
- Settlement lag from Razorpay adds another 2 days
- **Fix**: Incremental sync (fetch only new/modified records), Razorpay API webhooks

**Dimensional breakdown** (at scale):
- JSONB queries on `dimensions` slow down with millions of rows
- GROUP BY on high-cardinality fields (ad_id, SKU) explodes
- **Fix**: Columnar compression, materialized views, data warehouse (BigQuery/Snowflake)

---

## Hours Spent

- **Session 1** (May 16): Architecture decisions, scratchpad, project structure. ~4 hours
- **Session 2** (May 16–17): Core infrastructure (config, database, LLM client). ~6 hours
- **Session 3** (May 17): Data models (merchants, metrics, agent_log). ~5 hours
- **Session 4** (May 17–18): Normalization layer, all 3 connectors. ~8 hours
- **Session 5** (May 18): Chat layer (tools, loop, citations). ~5 hours
- **Session 6** (May 18): Agent (attribution, tasks, scheduler). ~6 hours
- **Session 7** (May 18): API routes (merchants, connectors, chat, agent). ~4 hours
- **Session 8** (May 18): Frontend (React + Vite, all pages). ~5 hours
- **Session 9** (May 18): Bug fixes, demo connector endpoint, README. ~3 hours

**Total**: ~46 hours across 9 sessions (about 1 week of focused work).

---

## What We'd Do With Another Week

1. **Incremental sync**: Fetch only new records, not full history. Speed up re-syncs 10x.

2. **Razorpay webhook integration**: Real-time settlement notifications instead of polling.

3. **Confidence score tuning**: Collect feedback on threshold accuracy. Adjust per merchant cohort.

4. **Multi-turn conversation memory**: Store chat history in database. Enable follow-up questions ("what about last month?").

5. **Agent email digest**: Summarize weekly findings, send to founder inbox. One-click action links.

6. **Attribution modeling**: Move past hardcoded thresholds. Simple Bayesian: "How likely is this ad campaign responsible for this order?"

7. **Testing harness**: Full unit + integration test suite. Mutation testing for agent logic.

8. **Observability**: Datadog/Honeycomb instrumentation. Track LLM latency, connector failures, agent accuracy.

9. **Self-serve connector UI**: Drag-drop field mapping. Let founders add custom connectors (Google Sheets, CSV).

10. **Production deployment**: AWS ASG + RDS + ALB + SQS wiring. Load testing. Runbook for incidents.

---

## Technical Decisions

All architectural decisions documented in [DECISIONS.md](./DECISIONS.md) (not present in this v0, but reference the scratchpad for full rationale).

---

## Limitations & Disclaimers

- **Mock connector configs**: Demo connectors are placeholders. They cannot sync real data. Register real credentials to test with live data.
- **Agent observes only**: Agent proposes recommendations. It does not execute actions (no order cancellations, ad spend adjustments, etc.). All actions require founder approval.
- **Settlement lag**: Razorpay settlements are 24–48 hours behind transaction. Agent analysis assumes 7-day window ending yesterday.
- **No live actions**: This is intentional. Full transparency, founder in control.

---

## Questions / Feedback

This is v0. Many rough edges. If you run into issues:

1. Check `.env.example` — make sure all required variables are set
2. Verify database is running: `psql -U d2c -d d2c -c "SELECT 1"`
3. Check Celery is running (if testing agent without `?sync=true`)
4. Frontend expects trailing slash: `/chat/` not `/chat`

For bugs or questions, reply to the email with:
- What you tried
- What error you got
- What you'd ship if we said "ship what you have"

---

## License

This project is built as part of an AI platform challenge. All code is provided as-is for evaluation purposes.
