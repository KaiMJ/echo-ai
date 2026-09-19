# Web search plan

## Goal

Give Echo a useful, local `web_search` tool that returns sources the agent can cite. The first version accepts one query, uses one configured search backend, fetches a few result pages over HTTP, and returns structured evidence. It does not require a commercial search API key.

The initial backend is a locally hosted SearXNG instance. SearXNG provides an HTTP search API and forwards queries to configured upstream engines. Echo should enable one upstream engine initially. SearXNG is a metasearch service, not an independent web index; upstream engines can throttle or block it.

## First version: one query

1. The model calls `web_search` with a single query string. Keep the existing `search` tool for workspace files.
2. Echo requests JSON results from the configured SearXNG endpoint. Return a clear error if the service is unavailable or no engine responds.
3. Select a small, configurable number of results (start with three), preserving the search title, snippet, URL, and rank.
4. Fetch selected pages with `httpx`, with timeouts, response size limits, redirect limits, and an HTML content-type check. A failed fetch must not erase the search result.
5. Extract page title, readable text, and a small set of useful links from the returned HTML. Remove scripts, styles, navigation, and repeated boilerplate where practical. Keep the extractor replaceable; HTTP fetching cannot see content rendered only by JavaScript.
6. Return the structured result to the agent. The agent can answer from fetched evidence and cite the corresponding page URLs. It must distinguish search snippets from fetched page content.

The tool returns data rather than asking a second model to summarize it. Bound the amount of extracted text per page and the total tool output so it fits the model context.

Example result shape (fields may evolve during implementation):

```json
{
  "query": "example query",
  "engine": "searxng",
  "results": [
    {
      "rank": 1,
      "title": "Example page",
      "search_url": "https://example.com/page",
      "snippet": "Search result snippet",
      "fetch": {
        "status": "ok",
        "final_url": "https://example.com/page",
        "fetched_at": "2026-09-19T12:00:00Z",
        "title": "Example page",
        "text": "Extracted readable text",
        "links": [{"text": "Related page", "url": "https://example.com/related"}]
      }
    }
  ]
}
```

For fetch failures, set `fetch.status` to a specific error value and omit unsupported page content. A citation to `final_url` should support a claim from fetched content; a search-only result should be identified as such. URL alone is not proof that a claim appears on the page.

## Integration in Echo

- Add the model-facing schema in `src/echo_ai/runtime/tools.py`, separate from workspace `search`.
- Add a web-search service for SearXNG requests, page fetching, and extraction. Keep backend and fetcher interfaces narrow so a browser fetcher can be added later.
- Route tool execution through the existing workspace dispatcher without a shell command. The host and Docker sandbox need an explicit way to reach the configured SearXNG address; `localhost` inside Docker refers to the container, not the host.
- Configure the endpoint, enabled state, result count, fetch limits, and timeouts. Do not hard-code a public SearXNG instance.
- Return per-result errors instead of failing the entire search when one page is unavailable. Respect cancellation from the agent loop.

Fetching arbitrary result URLs creates a network boundary. Reject non-HTTP schemes and private, loopback, or link-local destinations for page fetches, including after redirects and DNS resolution. The configured SearXNG endpoint is a separate trusted setting and may intentionally be local. Bound downloads and extracted output, and treat page text as untrusted tool data rather than instructions.

## Verification

- Use a local fake SearXNG response and fixture HTML to check result mapping, text/link extraction, redirects, and per-page failures.
- Check that a page fetch cannot access local network addresses and that response size and timeout limits hold.
- Run one live query against the configured local SearXNG instance to inspect result quality and blocked-engine behavior. Do not make live search a required test.

## Later stages

1. **Several queries and engines:** optionally have the model propose 3–10 queries, run them with bounded concurrency, deduplicate URLs, and merge results. Persist a batch timestamp and enforce the requested 10-minute interval before starting another batch. Limit upstream concurrency separately because each SearXNG query can fan out to several engines.
2. **Cache and retrieval:** save search metadata and fetched content with fetch times in SQLite; add text retrieval only when result volume warrants it. Refresh stale pages deliberately.
3. **JavaScript and interaction:** add an optional browser fetcher for pages whose useful content is absent from HTTP HTML, and an explicit browser interaction tool for user-requested actions. Headless and headful modes should share the same browser path. browser-use's DOM and accessibility representation is useful for interactive controls, but is more machinery than the first version needs for article extraction.
4. **Synthesis:** add a separate LLM summarization or retrieval pass only when direct agent use of bounded page text becomes inadequate. Keep source URLs attached to individual evidence chunks so generated citations remain traceable.

## References

- [SearXNG search API](https://docs.searxng.org/dev/search_api.html)
- [SearXNG limiter and upstream blocking](https://docs.searxng.org/admin/searx.limiter)
- [browser-use DOM service](https://github.com/browser-use/browser-use/blob/main/browser_use/dom/service.py)
- [browser-use DOM serializer](https://github.com/browser-use/browser-use/blob/main/browser_use/dom/serializer/serializer.py)
