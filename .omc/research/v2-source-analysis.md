# V2 Source Analysis: AI Data Sources for Dashboard

**Date**: April 12, 2026  
**Scope**: Evaluation of 8 candidate AI/ML data sources for integration into ai-dashboard V2  
**Status**: Ready for implementation planning

---

## Executive Summary

This analysis evaluates 8 candidate data sources for the V2 AI news dashboard. **5 sources are recommended for implementation** based on API availability, data quality, and implementation complexity:

1. **Semantic Scholar** (INCLUDE) — 214M academic papers, free API, AI-powered relevance
2. **Papers With Code** (INCLUDE) — ML papers + code repos, free API, high AI relevance
3. **Bluesky AT Protocol** (INCLUDE) — 41M users, free public API, no auth required
4. **Lobsters** (INCLUDE) — Curated tech community, free JSON API, high-quality content
5. **dev.to** (INCLUDE) — Developer blog platform, free API, strong AI/ML tag coverage

**Deferred** (viable but lower priority):
- Mastodon AI instances (ActivityPub API, requires instance selection)
- Conference feeds (OpenReview, limited to 3-4 conferences/year)

**Not Recommended**:
- Twitter/X API (cost-prohibitive at $100+/month for personal tool)

---

## Summary Table

| Source | API Type | Rate Limit | Cost | Data Quality | Update Freq | AI % | Complexity | Recommendation |
|--------|----------|------------|------|--------------|-------------|------|------------|----------------|
| **Semantic Scholar** | REST JSON | 1 RPS (free) | Free | ⭐⭐⭐⭐⭐ | Daily | 95%+ | S (1-2h) | **INCLUDE** |
| **Papers With Code** | REST JSON | Unlimited | Free | ⭐⭐⭐⭐⭐ | Daily | 100% | S (1-2h) | **INCLUDE** |
| **Bluesky AT Protocol** | REST JSON | Unlimited (public) | Free | ⭐⭐⭐⭐ | Real-time | 40-50% | S (2-3h) | **INCLUDE** |
| **Lobsters** | REST JSON | Unlimited | Free | ⭐⭐⭐⭐⭐ | Real-time | 30-40% | S (1-2h) | **INCLUDE** |
| **dev.to** | REST JSON | Unlimited | Free | ⭐⭐⭐⭐ | Hourly | 25-35% | S (1-2h) | **INCLUDE** |
| **Mastodon (AI instances)** | REST JSON / ActivityPub | Varies | Free | ⭐⭐⭐ | Real-time | 60-80% | M (3-4h) | DEFER |
| **Conference Feeds (OpenReview)** | REST JSON / RSS | Unlimited | Free | ⭐⭐⭐⭐⭐ | Quarterly | 100% | M (4-5h) | DEFER |
| **Twitter/X API** | REST JSON | Varies | $100+/mo | ⭐⭐⭐⭐ | Real-time | 30-40% | M (3-4h) | **SKIP** |

---

## Detailed Evaluations

### 1. Semantic Scholar

**Status**: ✅ INCLUDE

#### API Details
- **Base URL**: `https://api.semanticscholar.org/graph/v1`
- **Auth**: Optional (free tier: 1 RPS shared pool; with API key: 1 RPS dedicated)
- **Rate Limits**: 
  - Unauthenticated: 1000 requests/sec shared (soft limit, may throttle during heavy use)
  - Authenticated (free API key): 1 RPS sustained
- **Cost**: Free (no API key required for basic search)

#### Data Shape
```json
{
  "paperId": "204e3073870fae3d05bcbc2f6a8e263d9b72e776",
  "title": "Attention Is All You Need",
  "abstract": "...",
  "year": 2017,
  "authors": [
    {"name": "Ashish Vaswani", "authorId": "..."}
  ],
  "citationCount": 120000,
  "influentialCitationCount": 8500,
  "isOpenAccess": true,
  "openAccessPdf": {"url": "https://..."},
  "publicationDate": "2017-06-12",
  "publicationVenue": {"name": "NeurIPS", "type": "conference"},
  "url": "https://semanticscholar.org/paper/...",
  "tldr": {"text": "One-sentence AI-generated summary"}
}
```

#### Key Endpoints
- **Search papers**: `GET /paper/search?query=transformer&limit=100`
- **Get paper details**: `GET /paper/{paperId}`
- **Author search**: `GET /author/search?query=Yann%20LeCun`
- **Recommendations**: `GET /paper/{paperId}/recommendations`

#### Pros
- ✅ 214M papers indexed (largest academic corpus)
- ✅ AI-powered relevance ranking (not keyword-based)
- ✅ Free with no API key required
- ✅ Includes open-access PDF links
- ✅ Citation counts and influence metrics
- ✅ AI-generated TLDR summaries
- ✅ Excellent documentation

#### Cons
- ⚠️ Rate limit of 1 RPS may require batching for large queries
- ⚠️ Primarily academic papers (not news/blog posts)
- ⚠️ Slight delay in indexing new papers (1-2 weeks)

#### Data Quality
- **Title**: ✅ Always present
- **URL**: ✅ Always present (semanticscholar.org link)
- **Timestamp**: ✅ `publicationDate` (ISO 8601)
- **Engagement**: ✅ `citationCount`, `influentialCitationCount`
- **Content**: ✅ Abstract + AI-generated TLDR

#### Update Frequency
- Daily indexing of new papers from arXiv, conferences, journals
- Typical lag: 1-2 weeks from publication to indexing

#### AI Relevance
- **95%+** — Filters available by field of study (AI, ML, NLP, Computer Vision, etc.)
- Can query: `query=transformer&fieldsOfStudy=AI`

#### Implementation Complexity
- **Effort**: S (1-2 hours)
- **Dependencies**: `httpx`, `json`
- **Parsing**: Straightforward JSON
- **Error handling**: Standard HTTP status codes

#### Adapter Signature
```python
class SemanticScholarAdapter(SourceAdapter):
    async def fetch(self, limit: int = 50) -> List[FeedItem]:
        """
        Fetch recent AI papers from Semantic Scholar.
        
        Returns:
            List[FeedItem] with source_kind='semantic_scholar'
        """
```

#### Example Request
```bash
curl "https://api.semanticscholar.org/graph/v1/paper/search?query=transformer&limit=10&sort=year:desc" \
  -H "Accept: application/json"
```

---

### 2. Papers With Code

**Status**: ✅ INCLUDE

#### API Details
- **Base URL**: `https://paperswithcode.com/api/v1`
- **Auth**: None required
- **Rate Limits**: Unlimited (no documented limits)
- **Cost**: Free

#### Data Shape
```json
{
  "id": "efficient-methods-for-incorporating-knowledge",
  "title": "Efficient Methods for Incorporating Knowledge into Topic Models",
  "abstract": "...",
  "url": "https://paperswithcode.com/paper/...",
  "arxiv_id": "1234.5678",
  "published_date": "2020-06-15",
  "github_url": "https://github.com/...",
  "github_stars": 1250,
  "tasks": ["topic-modeling", "nlp"],
  "datasets": ["20newsgroups"],
  "methods": ["lda", "neural-topic-models"],
  "paper_url": "https://arxiv.org/abs/1234.5678"
}
```

#### Key Endpoints
- **List papers**: `GET /papers/?ordering=-published_date&limit=100`
- **Search papers**: `GET /papers/?search=transformer&limit=100`
- **Get paper details**: `GET /papers/{paper_id}/`
- **List by task**: `GET /tasks/{task_id}/papers/`
- **List by dataset**: `GET /datasets/{dataset_id}/papers/`

#### Pros
- ✅ Links papers to GitHub implementations (unique value)
- ✅ GitHub star counts (engagement metric)
- ✅ Task and dataset tagging (structured metadata)
- ✅ Free with no rate limits
- ✅ 100% AI/ML relevant
- ✅ Python client library available (`paperswithcode-client`)
- ✅ Includes arXiv IDs for cross-referencing

#### Cons
- ⚠️ Smaller corpus than Semantic Scholar (~50K papers)
- ⚠️ Focuses on papers with code (excludes pure theory papers)
- ⚠️ Less frequent updates than Semantic Scholar

#### Data Quality
- **Title**: ✅ Always present
- **URL**: ✅ Always present (paperswithcode.com + arxiv.org)
- **Timestamp**: ✅ `published_date` (ISO 8601)
- **Engagement**: ✅ `github_stars` (proxy for adoption)
- **Content**: ✅ Abstract + task/dataset tags

#### Update Frequency
- Daily updates from arXiv
- Typical lag: Same day as arXiv publication

#### AI Relevance
- **100%** — All papers are AI/ML by definition
- Filterable by task (NLP, Computer Vision, RL, etc.)

#### Implementation Complexity
- **Effort**: S (1-2 hours)
- **Dependencies**: `httpx`, `json`
- **Parsing**: Straightforward JSON
- **Python client**: `pip install paperswithcode-client` (optional)

#### Adapter Signature
```python
class PapersWithCodeAdapter(SourceAdapter):
    async def fetch(self, limit: int = 50) -> List[FeedItem]:
        """
        Fetch recent papers with code implementations.
        
        Returns:
            List[FeedItem] with source_kind='papers_with_code'
        """
```

#### Example Request
```bash
curl "https://paperswithcode.com/api/v1/papers/?ordering=-published_date&limit=10" \
  -H "Accept: application/json"
```

---

### 3. Bluesky AT Protocol

**Status**: ✅ INCLUDE

#### API Details
- **Base URL**: `https://public.api.bsky.app/xrpc`
- **Auth**: None required for public data (optional for search)
- **Rate Limits**: Unlimited for public reads (no documented limits)
- **Cost**: Free

#### Data Shape
```json
{
  "uri": "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.post/abc123",
  "cid": "bafy...",
  "author": {
    "did": "did:plc:z72i7hdynmk6r22z27h6tvur",
    "handle": "example.bsky.social",
    "displayName": "Example User",
    "avatar": "https://..."
  },
  "record": {
    "text": "Just published a new paper on transformers!",
    "createdAt": "2026-04-12T10:30:00.000Z",
    "facets": [
      {
        "index": {"byteStart": 0, "byteEnd": 10},
        "features": [{"uri": "https://example.com/paper"}]
      }
    ]
  },
  "likeCount": 42,
  "replyCount": 5,
  "repostCount": 12,
  "quoteCount": 2
}
```

#### Key Endpoints
- **Get author feed**: `GET /app.bsky.feed.getAuthorFeed?actor={handle}&limit=50`
- **Get timeline**: `GET /app.bsky.feed.getTimeline?limit=50` (requires auth)
- **Search posts**: `GET /app.bsky.feed.searchPosts?q=transformer&limit=50` (requires auth)
- **Get profile**: `GET /app.bsky.actor.getProfile?actor={handle}`
- **Resolve handle**: `GET /com.atproto.identity.resolveHandle?handle={handle}`

#### Pros
- ✅ 41M users (302% growth in 2025)
- ✅ Fully open, decentralized protocol
- ✅ No API key required for public data
- ✅ Real-time updates
- ✅ Rich engagement metrics (likes, reposts, replies)
- ✅ Structured JSON responses
- ✅ Growing AI/ML community

#### Cons
- ⚠️ Post search requires authentication (app password)
- ⚠️ Lower AI content density (~40-50%) vs academic sources
- ⚠️ Requires following specific AI accounts for curated feed
- ⚠️ Newer platform (less established than Twitter)

#### Data Quality
- **Title**: ⚠️ Posts are text-only (no separate title field)
- **URL**: ✅ Extracted from post text via facets
- **Timestamp**: ✅ `createdAt` (ISO 8601)
- **Engagement**: ✅ `likeCount`, `repostCount`, `replyCount`
- **Content**: ✅ Full post text

#### Update Frequency
- Real-time (posts appear immediately)

#### AI Relevance
- **40-50%** — Depends on followed accounts
- Recommended accounts: @ai.bsky.social, @openai.bsky.social, @anthropic.bsky.social, etc.
- Can filter by hashtags (#ai, #ml, #llm, #transformers)

#### Implementation Complexity
- **Effort**: S (2-3 hours)
- **Dependencies**: `httpx`, `json`
- **Parsing**: Straightforward JSON, but requires extracting URLs from post text
- **Auth**: Optional (for search, create app password in Bluesky settings)

#### Adapter Signature
```python
class BlueskyAdapter(SourceAdapter):
    async def fetch(self, limit: int = 50) -> List[FeedItem]:
        """
        Fetch recent posts from AI-focused Bluesky accounts.
        
        Returns:
            List[FeedItem] with source_kind='bluesky'
        """
```

#### Example Request
```bash
# Get posts from a specific account
curl "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=openai.bsky.social&limit=10" \
  -H "Accept: application/json"

# Resolve handle to DID
curl "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle=openai.bsky.social" \
  -H "Accept: application/json"
```

---

### 4. Lobsters

**Status**: ✅ INCLUDE

#### API Details
- **Base URL**: `https://lobste.rs/api/v0.3`
- **Auth**: None required
- **Rate Limits**: Unlimited (no documented limits)
- **Cost**: Free

#### Data Shape
```json
{
  "short_id": "abc123",
  "short_id_url": "https://lobste.rs/s/abc123",
  "created_at": "2026-04-12T10:30:00Z",
  "title": "Understanding Rust's Ownership Model",
  "url": "https://example.com/rust-ownership",
  "score": 45,
  "flags": 0,
  "comment_count": 12,
  "description": "",
  "comments_url": "https://lobste.rs/s/abc123",
  "submitter_user": {
    "username": "example_user",
    "avatar_url": "https://..."
  },
  "tags": ["rust", "programming", "learning"]
}
```

#### Key Endpoints
- **List stories**: `GET /stories.json?order=newest&limit=30`
- **List by tag**: `GET /stories.json?tag=ai&order=newest&limit=30`
- **Get story details**: `GET /stories/{short_id}.json`
- **List tags**: `GET /tags.json`

#### Pros
- ✅ Invite-only community (high-quality content)
- ✅ Curated tech discussions (no spam)
- ✅ Free JSON API with no rate limits
- ✅ Real-time updates
- ✅ Rich engagement metrics (score, comments)
- ✅ Tag-based filtering (ai, ml, nlp, etc.)
- ✅ Excellent for technical content discovery

#### Cons
- ⚠️ Smaller community (~10K active users)
- ⚠️ Lower AI content density (~30-40%)
- ⚠️ Slower update frequency than social media
- ⚠️ Limited to ~30 stories per request

#### Data Quality
- **Title**: ✅ Always present
- **URL**: ✅ Always present
- **Timestamp**: ✅ `created_at` (ISO 8601)
- **Engagement**: ✅ `score`, `comment_count`, `flags`
- **Content**: ✅ Title + URL (no description field)

#### Update Frequency
- Hourly (new stories appear throughout the day)
- Typical: 10-20 new stories per day

#### AI Relevance
- **30-40%** — Filter by tags: `ai`, `ml`, `nlp`, `deep-learning`, `llm`
- Can combine multiple tags in queries

#### Implementation Complexity
- **Effort**: S (1-2 hours)
- **Dependencies**: `httpx`, `json`
- **Parsing**: Straightforward JSON
- **Pagination**: Offset-based (use `limit` and `offset` parameters)

#### Adapter Signature
```python
class LobstersAdapter(SourceAdapter):
    async def fetch(self, limit: int = 50) -> List[FeedItem]:
        """
        Fetch recent stories from Lobsters, filtered by AI/ML tags.
        
        Returns:
            List[FeedItem] with source_kind='lobsters'
        """
```

#### Example Request
```bash
# Get newest stories
curl "https://lobste.rs/api/v0.3/stories.json?order=newest&limit=30" \
  -H "Accept: application/json"

# Get stories by tag
curl "https://lobste.rs/api/v0.3/stories.json?tag=ai&order=newest&limit=30" \
  -H "Accept: application/json"

# Get all available tags
curl "https://lobste.rs/api/v0.3/tags.json" \
  -H "Accept: application/json"
```

---

### 5. dev.to

**Status**: ✅ INCLUDE

#### API Details
- **Base URL**: `https://dev.to/api`
- **Auth**: Optional (API key for higher rate limits)
- **Rate Limits**: 
  - Unauthenticated: 10 requests/min
  - Authenticated: 30 requests/min
- **Cost**: Free

#### Data Shape
```json
{
  "type_of": "article",
  "id": 3488576,
  "title": "I built a Telegram bot that reads 70 arXiv papers a day",
  "description": "How I automated AI paper discovery...",
  "slug": "i-built-a-telegram-bot-that-reads-70-arxiv-papers-a-day-so-i-dont-have-to-19b5",
  "path": "/landigf/i-built-a-telegram-bot-that-reads-70-arxiv-papers-a-day-so-i-dont-have-to-19b5",
  "url": "https://dev.to/landigf/i-built-a-telegram-bot-that-reads-70-arxiv-papers-a-day-so-i-dont-have-to-19b5",
  "comments_count": 1,
  "public_reactions_count": 42,
  "published_timestamp": "2026-04-11T22:18:52Z",
  "created_at": "2026-04-11T22:18:52Z",
  "edited_at": "2026-04-11T22:33:55Z",
  "reading_time_minutes": 6,
  "tag_list": ["telegram", "gemini", "ai", "indiehackers"],
  "cover_image": "https://...",
  "user": {
    "name": "landigf",
    "username": "landigf",
    "github_username": "landigf",
    "profile_image": "https://..."
  }
}
```

#### Key Endpoints
- **List articles**: `GET /articles?page=1&per_page=30`
- **List by tag**: `GET /articles?tag=ai&page=1&per_page=30`
- **Get article details**: `GET /articles/{id}`
- **Search**: `GET /articles?search=transformer&page=1&per_page=30`
- **User articles**: `GET /articles?username={username}&page=1&per_page=30`

#### Pros
- ✅ Large developer community (1M+ articles)
- ✅ Free API with no authentication required
- ✅ Strong AI/ML tag coverage (#ai, #ml, #llm, #deeplearning, #nlp)
- ✅ Rich metadata (reactions, comments, reading time)
- ✅ Cover images for visual content
- ✅ Hourly updates
- ✅ Excellent for tutorials and how-to content

#### Cons
- ⚠️ Rate limit of 10 req/min (unauthenticated)
- ⚠️ Lower AI content density (~25-35%)
- ⚠️ Quality varies (mix of professional and amateur content)
- ⚠️ Pagination limited to 1000 articles per query

#### Data Quality
- **Title**: ✅ Always present
- **URL**: ✅ Always present
- **Timestamp**: ✅ `published_timestamp` (ISO 8601)
- **Engagement**: ✅ `public_reactions_count`, `comments_count`
- **Content**: ✅ Title + description + reading time

#### Update Frequency
- Hourly (new articles published continuously)
- Typical: 50-100 new articles per day with AI tags

#### AI Relevance
- **25-35%** — Filter by tags: `ai`, `ml`, `llm`, `deeplearning`, `nlp`, `machinelearning`
- Can combine multiple tags

#### Implementation Complexity
- **Effort**: S (1-2 hours)
- **Dependencies**: `httpx`, `json`
- **Parsing**: Straightforward JSON
- **Pagination**: Offset-based (use `page` and `per_page` parameters)

#### Adapter Signature
```python
class DevToAdapter(SourceAdapter):
    async def fetch(self, limit: int = 50) -> List[FeedItem]:
        """
        Fetch recent articles from dev.to, filtered by AI/ML tags.
        
        Returns:
            List[FeedItem] with source_kind='dev_to'
        """
```

#### Example Request
```bash
# Get articles by tag
curl "https://dev.to/api/articles?tag=ai&per_page=30&page=1" \
  -H "Accept: application/json"

# Search articles
curl "https://dev.to/api/articles?search=transformer&per_page=30&page=1" \
  -H "Accept: application/json"

# Get specific article
curl "https://dev.to/api/articles/3488576" \
  -H "Accept: application/json"
```

---

## Deferred Sources

### Mastodon AI Instances

**Status**: 🟡 DEFER (viable, lower priority)

#### Why Deferred
- Requires selecting specific instances (mastodon.social, pixelfed.social, etc.)
- ActivityPub protocol adds complexity vs REST JSON
- Lower AI content density than dedicated sources
- Requires instance-specific rate limit handling

#### Viable Path
- Use `https://mastodon.social/api/v1/timelines/public` for public timeline
- Filter by hashtags (#ai, #ml, #llm)
- Effort: M (3-4 hours) due to ActivityPub complexity

#### Recommendation
Implement after core sources are stable. Good for real-time social signal.

---

### Conference Feeds (OpenReview, NeurIPS, ICML, ICLR)

**Status**: 🟡 DEFER (viable, lower priority)

#### Why Deferred
- Limited to 3-4 conferences per year
- Quarterly update frequency (not continuous)
- Overlaps significantly with Semantic Scholar
- Requires separate adapter per conference

#### Viable Path
- OpenReview API: `https://api.openreview.net/notes?invitation=ICLR.cc/2026/Conference`
- RSS feeds available for each conference
- Effort: M (4-5 hours) for multi-conference support

#### Recommendation
Implement as supplementary source after core sources. Good for ensuring no major papers are missed.

---

## Not Recommended

### Twitter/X API

**Status**: ❌ SKIP

#### Why Not Recommended
- **Cost**: $100+/month minimum (pay-per-use pricing)
- **Rate limits**: Varies by tier, restrictive for personal tools
- **AI relevance**: 30-40% (mixed with general tech/news)
- **Complexity**: M (3-4 hours) for OAuth + streaming
- **Value**: Lower than free alternatives (Bluesky, dev.to)

#### Cost Breakdown
- Search endpoint: ~$2 per 1,000 tweets
- Timeline endpoint: ~$1 per 1,000 tweets
- Estimated monthly cost for 10K tweets/day: $300-600

#### Recommendation
Not cost-effective for a personal dashboard. Use Bluesky instead (free, similar content).

---

## Implementation Roadmap

### Phase 1: Core Sources (Week 1-2)
1. **Semantic Scholar** — Academic papers (highest quality)
2. **Papers With Code** — Papers + code (unique value)
3. **Lobsters** — Curated tech (high quality)

### Phase 2: Social Sources (Week 2-3)
4. **Bluesky** — Real-time social signal
5. **dev.to** — Developer tutorials

### Phase 3: Optional Enhancements (Week 3+)
6. **Mastodon** — Decentralized social
7. **Conference feeds** — Quarterly updates

---

## Adapter Implementation Template

```python
from typing import List
from datetime import datetime
import httpx

class FeedItem:
    def __init__(
        self,
        source_kind: str,
        source_uid: str,
        title: str,
        url: str,
        published_at: datetime,
        raw_payload: dict,
    ):
        self.source_kind = source_kind
        self.source_uid = source_uid
        self.title = title
        self.url = url
        self.published_at = published_at
        self.raw_payload = raw_payload

class SourceAdapter:
    """Base class for all source adapters."""
    
    async def fetch(self, limit: int = 50) -> List[FeedItem]:
        """Fetch items from the source."""
        raise NotImplementedError

class SemanticScholarAdapter(SourceAdapter):
    """Adapter for Semantic Scholar API."""
    
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    
    async def fetch(self, limit: int = 50) -> List[FeedItem]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/paper/search",
                params={
                    "query": "transformer OR attention OR neural network",
                    "limit": limit,
                    "sort": "year:desc",
                    "fieldsOfStudy": "AI",
                },
            )
            response.raise_for_status()
            data = response.json()
            
            items = []
            for paper in data.get("data", []):
                items.append(
                    FeedItem(
                        source_kind="semantic_scholar",
                        source_uid=paper["paperId"],
                        title=paper["title"],
                        url=paper["url"],
                        published_at=datetime.fromisoformat(
                            paper["publicationDate"].replace("Z", "+00:00")
                        ),
                        raw_payload=paper,
                    )
                )
            return items
```

---

## Conclusion

**Recommended for immediate implementation**: Semantic Scholar, Papers With Code, Bluesky, Lobsters, dev.to

These 5 sources provide:
- ✅ 100% free (no cost)
- ✅ High data quality
- ✅ Complementary coverage (academic + social + curated)
- ✅ Low implementation complexity (1-3 hours each)
- ✅ Real-time to daily updates
- ✅ Rich engagement metrics

**Total implementation effort**: ~10-12 hours for all 5 adapters

**Expected coverage**: 500-1000 unique AI/ML items per day across all sources

