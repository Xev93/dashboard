from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceDef:
    kind: str
    module: str
    class_name: str
    tab_label: str
    tier: str
    content_mode: str
    engagement_key: str | None = None
    default_options: dict[str, object] = field(default_factory=dict)
    enabled: bool = True


SOURCE_CATALOG: tuple[SourceDef, ...] = (
    SourceDef(
        kind="arxiv",
        module="ai_dashboard.sources.arxiv",
        class_name="ArxivAdapter",
        tab_label="AX",
        tier="first_party",
        content_mode="arxiv",
    ),
    SourceDef(
        kind="core",
        module="ai_dashboard.sources.core",
        class_name="CoreAdapter",
        tab_label="CO",
        tier="aggregator",
        content_mode="payload:abstract",
        default_options={"query": "artificial intelligence machine learning"},
        enabled=False,
    ),
    SourceDef(
        kind="dblp",
        module="ai_dashboard.sources.dblp",
        class_name="DblpAdapter",
        tab_label="DB",
        tier="first_party",
        content_mode="web_article",
        default_options={"venues": ["NeurIPS", "ICML", "CVPR", "ICLR", "AAAI"]},
    ),
    SourceDef(
        kind="hn",
        module="ai_dashboard.sources.hackernews",
        class_name="HackerNewsAdapter",
        tab_label="HN",
        tier="community",
        content_mode="web_article",
        engagement_key="points",
        default_options={
            "keywords": [
                "AI",
                "ML",
                "LLM",
                "GPT",
                "Claude",
                "OpenAI",
                "Anthropic",
                "neural",
                "transformer",
                "diffusion",
                "agent",
                "LoRA",
                "fine-tun",
                "embedding",
                "RAG",
                "deep learning",
                "prompt",
            ]
        },
    ),
    SourceDef(
        kind="github_trending",
        module="ai_dashboard.sources.github_trending",
        class_name="GithubTrendingAdapter",
        tab_label="GH",
        tier="community",
        content_mode="github_readme",
        engagement_key="stars",
    ),
    SourceDef(
        kind="hal",
        module="ai_dashboard.sources.hal",
        class_name="HalAdapter",
        tab_label="HL",
        tier="first_party",
        content_mode="web_article",
        default_options={
            "query": "artificial intelligence OR machine learning",
            "domain": "info",
        },
    ),
    SourceDef(
        kind="huggingface",
        module="ai_dashboard.sources.huggingface",
        class_name="HuggingFaceAdapter",
        tab_label="HF",
        tier="community",
        content_mode="hf_card",
        engagement_key="likes",
    ),
    SourceDef(
        kind="lab_blog",
        module="ai_dashboard.sources.lab_blog",
        class_name="LabBlogAdapter",
        tab_label="LB",
        tier="first_party",
        content_mode="web_article",
    ),
    SourceDef(
        kind="newsletter",
        module="ai_dashboard.sources.newsletter",
        class_name="NewsletterAdapter",
        tab_label="NL",
        tier="community",
        content_mode="web_article",
        default_options={
            "feeds": [
                "https://jack-clark.net/feed/",
                "https://www.deeplearning.ai/the-batch/feed/",
                "https://tldr.tech/api/rss/ai",
            ]
        },
    ),
    SourceDef(
        kind="openreview",
        module="ai_dashboard.sources.openreview",
        class_name="OpenReviewAdapter",
        tab_label="OR",
        tier="first_party",
        content_mode="web_article",
        enabled=False,
        default_options={
            "venues": ["NeurIPS.cc/2025/Conference", "ICLR.cc/2025/Conference"]
        },
    ),
    SourceDef(
        kind="papers_with_code",
        module="ai_dashboard.sources.papers_with_code",
        class_name="PapersWithCodeAdapter",
        tab_label="PW",
        tier="aggregator",
        content_mode="payload:abstract",
    ),
    SourceDef(
        kind="reddit",
        module="ai_dashboard.sources.reddit",
        class_name="RedditAdapter",
        tab_label="RD",
        tier="community",
        content_mode="payload:selftext",
        engagement_key="score",
        default_options={"subreddits": ["MachineLearning", "artificial", "LocalLLaMA"]},
    ),
    SourceDef(
        kind="semantic_scholar",
        module="ai_dashboard.sources.semantic_scholar",
        class_name="SemanticScholarAdapter",
        tab_label="S2",
        tier="aggregator",
        content_mode="payload:abstract",
        default_options={"query": "artificial intelligence machine learning"},
    ),
)

CATALOG_BY_KIND: dict[str, SourceDef] = {
    source.kind: source for source in SOURCE_CATALOG
}
ALL_KINDS: tuple[str, ...] = tuple(source.kind for source in SOURCE_CATALOG)
FIRST_PARTY_KINDS: frozenset[str] = frozenset(
    source.kind for source in SOURCE_CATALOG if source.tier == "first_party"
)
ENGAGEMENT_KEYS: dict[str, str] = {
    source.kind: source.engagement_key
    for source in SOURCE_CATALOG
    if source.engagement_key is not None
}
_TAB_ORDER: tuple[str, ...] = (
    "arxiv",
    "core",
    "dblp",
    "hn",
    "github_trending",
    "hal",
    "huggingface",
    "newsletter",
    "openreview",
    "reddit",
    "semantic_scholar",
    "lab_blog",
    "papers_with_code",
)
TAB_ENTRIES: tuple[tuple[str, str | None], ...] = (("All", None),) + tuple(
    (CATALOG_BY_KIND[kind].tab_label, kind) for kind in _TAB_ORDER
)
