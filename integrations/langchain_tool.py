"""LangChain tool wrapper for Disco (Discovery Engine).

Install: pip install discovery-engine-api langchain-core
Usage:
    from langchain_tool import DiscoTool
    tool = DiscoTool(api_key="disco_...")
    result = tool.invoke({"file_url": "https://example.com/data.csv", "target_column": "outcome"})
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class DiscoInput(BaseModel):
    """Input for the Disco discovery tool."""

    file_url: str = Field(description="URL of the tabular dataset to analyse (CSV, Excel, Parquet, JSON, etc.)")
    target_column: str = Field(description="The column to predict/explain — the outcome you want to understand")
    visibility: str = Field(
        default="public",
        description="'public' (free, results published) or 'private' (costs credits, results private)",
    )
    analysis_depth: int = Field(
        default=2,
        description="Analysis depth — higher means deeper analysis but more credits. Default 2.",
    )
    excluded_columns: list[str] = Field(
        default_factory=list,
        description="Columns to exclude (IDs, data leakage, tautological columns)",
    )
    use_llms: bool = Field(
        default=False,
        description="If True, enables LLM-powered summaries, literature context, and novelty assessment. Slower and more expensive. Public runs always use LLMs.",
    )


class DiscoTool(BaseTool):
    """Superhuman exploratory data analysis.

    Disco finds novel, statistically validated patterns in tabular data — the
    feature interactions, subgroup effects, and conditional relationships that
    correlation analysis, LLMs, and manual exploration miss. Every finding comes
    with p-values, effect sizes, and academic literature citations.

    Free for public data. No ML expertise required.
    """

    name: str = "disco"
    description: str = (
        "Automated scientific discovery from tabular data. Use when you need to find "
        "patterns, interactions, or subgroup effects in a dataset — especially when you "
        "don't know what to look for. Returns statistically validated patterns with "
        "p-values, effect sizes, and literature citations. Free for public data."
    )
    args_schema: type[BaseModel] = DiscoInput
    api_key: str = ""

    def __init__(self, api_key: str, **kwargs: Any):
        super().__init__(api_key=api_key, **kwargs)

    def _run(self, **kwargs: Any) -> str:
        return asyncio.run(self._arun(**kwargs))

    async def _arun(
        self,
        file_url: str,
        target_column: str,
        visibility: str = "public",
        analysis_depth: int = 2,
        excluded_columns: list[str] | None = None,
        use_llms: bool = False,
    ) -> str:
        from discovery import Engine

        engine = Engine(api_key=self.api_key)

        result = await engine.discover(
            file=file_url,
            target_column=target_column,
            visibility=visibility,
            analysis_depth=analysis_depth,
            excluded_columns=excluded_columns or [],
            use_llms=use_llms,
        )

        patterns = []
        for p in result.patterns:
            patterns.append({
                "description": p.description,
                "conditions": p.conditions,
                "p_value": p.p_value,
                "effect_size": p.abs_target_change,
                "direction": p.target_change_direction,
                "support_count": p.support_count,
                "support_percentage": p.support_percentage,
                "novelty": p.novelty_type,
                "novelty_explanation": p.novelty_explanation,
                "citations": p.citations,
            })

        output = {
            "report_url": result.report_url,
            "pattern_count": len(patterns),
            "patterns": patterns,
        }

        if hasattr(result, "summary") and result.summary:
            output["summary"] = result.summary.overview

        return json.dumps(output, indent=2, default=str)
