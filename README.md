# Discovery Engine

Find novel, statistically validated patterns in tabular data — feature interactions, subgroup effects, and conditional relationships that correlation analysis and LLMs miss.

Made by [Leap Laboratories](https://www.leap-labs.com).

## What It Does

Discovery Engine is a discovery pipeline, not an AI data analyst. It finds patterns you would not think to look for — complex feature interactions, threshold effects, subgroup differences — validates each on hold-out data with FDR-corrected p-values, and checks every finding against academic literature for novelty. Returns structured results with conditions, effect sizes, p-values, citations, and novelty scores.

**Use it when you want:** "what's really driving X?", "find something we're missing", "discover non-obvious patterns"

**Not for:** summary statistics, visualisation, filtering, SQL queries

## Get an API Key

Sign up from the command line — no password, no credit card:

```bash
# Step 1: Request verification code
curl -X POST https://disco.leap-labs.com/api/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com"}'
# → {"status": "verification_required", "email": "you@example.com"}

# Step 2: Submit code from email
curl -X POST https://disco.leap-labs.com/api/signup/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "code": "123456"}'
# → {"key": "disco_...", "credits": 10, "tier": "free_tier"}
```

Or create a key at [disco.leap-labs.com/developers](https://disco.leap-labs.com/developers).

Free tier: 10 credits/month for private runs, unlimited public runs. No card required.

## Python SDK

```bash
pip install discovery-engine-api
```

```python
from discovery import Engine

engine = Engine(api_key="disco_...")
result = await engine.discover(
    file="data.csv",
    target_column="outcome",
)

for pattern in result.patterns:
    if pattern.p_value < 0.05 and pattern.novelty_type == "novel":
        print(f"{pattern.description} (p={pattern.p_value:.4f})")

print(f"Full report: {result.report_url}")
```

→ [Full Python SDK reference](docs/python-sdk.md) · [Example notebook](notebooks/quickstart.ipynb)

## MCP Server

For AI agents. Add to your MCP config:

```json
{
  "mcpServers": {
    "discovery-engine": {
      "url": "https://disco.leap-labs.com/mcp",
      "env": { "DISCOVERY_API_KEY": "disco_..." }
    }
  }
}
```

→ [Agent skill file](SKILL.md)

## Pricing

| | Cost |
|---|---|
| Public runs | Free (results published, depth locked to 1) |
| Private runs | 1 credit per MB per depth iteration ($1.00/credit) |
| Free tier | 10 credits/month, no card required |
| Researcher | $49/month, 50 credits |
| Team | $199/month, 200 credits |

## Links

- [Dashboard](https://disco.leap-labs.com)
- [API keys](https://disco.leap-labs.com/developers)
- [Agent integration](https://disco.leap-labs.com/agents)
- [LLM-friendly reference](llms.txt)
- [OpenAPI spec](https://disco.leap-labs.com/.well-known/openapi.json)
- [Python SDK on PyPI](https://pypi.org/project/discovery-engine-api/)


## License

MIT