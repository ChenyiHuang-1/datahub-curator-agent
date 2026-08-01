# 🕵️ Sherlock — the Metadata Detective for DataHub

> Your data catalog has cold cases: tables nobody documented, nobody owns, and
> nobody dares to delete. Sherlock investigates them like a detective — and files
> the knowledge **back into the graph** where everyone (human or agent) inherits it.

Built for **[Build with DataHub: The Agent Hackathon](https://datahub.devpost.com/)**
— Track 1 (*Agents That Do Real Work*).

## What it does

Every patrol, Sherlock:

1. **🧊 Finds cold cases** — searches the graph via the [DataHub MCP Server](https://docs.datahub.com/docs/features/feature-guides/mcp)
   for datasets with no owner, no description, or mostly-undocumented columns.
2. **🔍 Gathers evidence** — for each case it pulls the schema
   (`list_schema_fields`), upstream/downstream lineage (`get_lineage`), **real SQL
   queries** that reference the table (`get_dataset_queries`), and sibling table
   names for naming-convention context.
3. **🧠 Deduces** — an LLM reasons over the evidence bundle and produces *grounded*
   deductions with confidence scores: what the table is for, what each column
   means, who plausibly owns it (from query authors and upstream ownership), and
   which columns look like **undeclared PII**.
4. **✍️ Writes it back** — via MCP mutation tools:
   - table & column descriptions (`update_description`), clearly marked as AI-generated
   - `PII-Suspect` tags on risky columns (`add_tags`)
   - a full **Case Report** document saved into DataHub (`save_document`) with the
     evidence chain, so the *next* agent (or human) doesn't start from zero
5. **📈 Remembers** — case reports live in the graph; future patrols read them and
   skip solved cases. Knowledge compounds.

Low-confidence deductions are **not** written (`--min-confidence`, default 0.5).
Ownership is *suggested* in the case report, never silently assigned.

## Why this matters

Undocumented, orphaned tables are the #1 way data catalogs rot. Documentation
sprints don't scale; humans hate writing metadata. An agent that turns the
evidence you *already have* (lineage + query logs + schemas) into documentation —
and contributes it back to the graph — makes the catalog self-healing.

## Quickstart

Prereqs: Python 3.10+, a DataHub instance (quickstart is fine), and any
OpenAI-compatible LLM endpoint.

```bash
git clone https://github.com/ChenyiHuang-1/datahub-curator-agent
cd datahub-curator-agent
pip install -e . mcp-server-datahub acryl-datahub

# point at your DataHub + LLM
export DATAHUB_GMS_URL=http://localhost:8080
export DATAHUB_GMS_TOKEN=...            # if auth is enabled
export SHERLOCK_LLM_API_KEY=sk-...      # any OpenAI-compatible key
# optional: SHERLOCK_LLM_BASE_URL, SHERLOCK_LLM_MODEL (default gpt-4o-mini)

# (demo) seed a deliberately messy e-commerce estate
python demo/seed_messy_estate.py

# patrol!
sherlock patrol --dry-run       # investigate only, print what it would do
sherlock patrol                 # investigate and write back
sherlock tools                  # list MCP tools from the connected server
```

## Architecture

```
┌────────────┐   search/get_entities   ┌──────────────────┐
│   Patrol   │ ───────────────────────▶ │                  │
│  (scanner) │                          │  DataHub MCP     │
└─────┬──────┘                          │  Server          │
      │ cold cases                      │  (stdio)         │
┌─────▼──────┐  schema/lineage/queries  │                  │
│Investigator│ ───────────────────────▶ │                  │
└─────┬──────┘                          └──────────────────┘
      │ evidence bundle                          ▲
┌─────▼──────┐                                   │ update_description
│  Deduction │  LLM (any OpenAI-compatible)      │ add_tags
│   engine   │                                   │ save_document
└─────┬──────┘                                   │
      │ deductions + confidence                  │
┌─────▼──────┐                                   │
│   Scribe   │ ──────────────────────────────────┘
└────────────┘        writes knowledge BACK into the graph
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Running on a schedule

Sherlock is designed to run unattended. `examples/github-action.yml` shows a
nightly patrol via GitHub Actions; any cron works.

## Safety properties

- **Grounded**: the LLM only sees evidence from the graph; deductions cite it.
- **Confidence-gated**: below-threshold deductions are logged, not written.
- **Attributed**: every write is marked as AI-generated with a link back here.
- **Reversible**: descriptions/tags are normal DataHub edits; case reports are
  plain documents.
- **Governance-aware**: owners are proposed in the report for human confirmation.

## License

Apache 2.0 — see [LICENSE](LICENSE).
