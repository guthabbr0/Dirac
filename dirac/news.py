from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import httpx


NEWS_CHANNEL_ID = '1506027063512141896'
KNOWN_NEWS_LIMIT = 3
EXPLORATORY_NEWS_LIMIT = 5
TECH_NEWS_MAX_ITEMS = KNOWN_NEWS_LIMIT
ARTIFICIAL_ANALYSIS_ARTICLES_URL = 'https://artificialanalysis.ai/articles'
AI_TECH_NEWS_FEEDS = [
    ('Hugging Face Blog', 'https://huggingface.co/blog/feed.xml'),
    ('arXiv cs.AI', 'https://rss.arxiv.org/rss/cs.AI'),
    ('arXiv cs.LG', 'https://rss.arxiv.org/rss/cs.LG'),
    ('arXiv cs.CL', 'https://rss.arxiv.org/rss/cs.CL'),
]
EXPLORATORY_NEWS_QUERIES = [
    'latest AI model release benchmark agentic AI',
    'new AI model benchmark release this week',
    'AI agent framework model release research benchmark',
    'open source AI model release benchmark',
    'AI coding agent model benchmark latest',
]
TECH_NEWS_EXCLUDED_TERMS = [
    'bomb', 'war', 'missile', 'invasion', 'attack', 'killed', 'death',
    'ebola', 'outbreak', 'earthquake', 'flood', 'hurricane', 'crime',
]
RECENT_POSTED_HOURS = 72
FRESH_DAYS = 14


def utc_now() -> str:
    n = datetime.now(timezone.utc).replace(tzinfo=None)
    return n.strftime('%Y-%m-%dT%H:%M:%S.') + f'{n.microsecond // 1000:03d}Z'


def utc_after_hours(hours: int) -> str:
    n = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=int(hours))
    return n.strftime('%Y-%m-%dT%H:%M:%S.') + f'{n.microsecond // 1000:03d}Z'


def normalize_news_text(text: Any) -> str:
    cleaned = str(text or '').replace('\\u0026', '&').replace('\\"', '"')
    cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
    cleaned = html.unescape(cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()


def normalize_news_url(url: Any) -> str:
    value = html.unescape(str(url or '').strip())
    if value.startswith('//duckduckgo.com/l/?') or value.startswith('https://duckduckgo.com/l/?'):
        parsed = urlparse(value if value.startswith('http') else 'https:' + value)
        uddg = parse_qs(parsed.query).get('uddg')
        if uddg:
            value = unquote(uddg[0])
    return value


def normalize_news_key(title: Any) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', normalize_news_text(title).lower()).strip()


def tech_news_limit(limit):
    try:
        requested = int(limit)
    except Exception:
        requested = TECH_NEWS_MAX_ITEMS
    return max(1, min(requested, TECH_NEWS_MAX_ITEMS))


def is_acceptable_tech_news(title):
    low = normalize_news_text(title).lower()
    return bool(low) and not any(term in low for term in TECH_NEWS_EXCLUDED_TERMS)


def parse_news_date(value: Any) -> str | None:
    text = normalize_news_text(value)
    if not text:
        return None
    candidates = [text]
    candidates.extend(re.findall(r'\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-]+Z?)?', text))
    for candidate in candidates:
        cleaned = candidate.strip()
        if not cleaned:
            continue
        try:
            dt = parsedate_to_datetime(cleaned)
        except Exception:
            try:
                dt = datetime.fromisoformat(cleaned.replace('Z', '+00:00'))
            except Exception:
                continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'
    return None


def date_status(published_at_utc: str | None) -> str:
    if not published_at_utc:
        return 'unknown'
    try:
        dt = datetime.fromisoformat(published_at_utc.replace('Z', '+00:00'))
    except Exception:
        return 'unknown'
    age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return 'fresh' if age <= timedelta(days=FRESH_DAYS) else 'older'


def news_item(title, url, source, source_kind, published_at_utc=None, metadata=None):
    normalized_title = normalize_news_text(title)
    normalized_url = normalize_news_url(url)
    if not normalized_title or not normalized_url or not is_acceptable_tech_news(normalized_title):
        return None
    published = parse_news_date(published_at_utc)
    item = {
        'title': normalized_title,
        'url': normalized_url,
        'link': normalized_url,
        'source': source,
        'source_kind': source_kind,
        'published_at_utc': published,
        'date_status': date_status(published),
        'metadata': dict(metadata or {}),
    }
    return item


def rss_text(elem, names):
    for name in names:
        found = elem.find(name)
        if found is not None and found.text:
            return found.text.strip()
    return ''


def atom_link(elem):
    link_node = elem.find('{http://www.w3.org/2005/Atom}link')
    return link_node.get('href', '') if link_node is not None else ''


async def fetch_artificial_analysis_articles(client, limit=1):
    items = []
    try:
        r = await client.get(ARTIFICIAL_ANALYSIS_ARTICLES_URL)
        if r.status_code != 200:
            return items
        body = r.text
        patterns = [
            r'\\"href\\":\\"(/articles/[^"\\]+)\\".*?\\"children\\":\\"([^"\\]+)\\"',
            r'"href"\s*:\s*"(/articles/[^"]+)".*?"children"\s*:\s*"([^"]+)"',
            r'href="(/articles/[^"]+)".{0,2500}?<h3[^>]*>(.*?)</h3>',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, body, re.S):
                path, title = match.groups()
                link = 'https://artificialanalysis.ai' + path
                item = news_item(title, link, 'Artificial Analysis', 'grounding')
                if item and item['url'] not in {i['url'] for i in items}:
                    items.append(item)
                if len(items) >= limit:
                    return items
            if items:
                break
    except Exception:
        return items
    return items[:limit]


async def fetch_known_news(limit=KNOWN_NEWS_LIMIT):
    lim = max(1, int(limit or KNOWN_NEWS_LIMIT))
    items = []
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        for item in await fetch_artificial_analysis_articles(client, 1):
            items.append(item)
        for source, url in AI_TECH_NEWS_FEEDS:
            if len(items) >= lim:
                break
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                root = ET.fromstring(r.content)
                entries = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
                for e in entries[:lim * 6]:
                    title = rss_text(e, ['title', '{http://www.w3.org/2005/Atom}title'])
                    link = rss_text(e, ['link', '{http://www.w3.org/2005/Atom}link']) or atom_link(e)
                    published = rss_text(e, ['pubDate', 'published', 'updated', '{http://www.w3.org/2005/Atom}published', '{http://www.w3.org/2005/Atom}updated'])
                    item = news_item(title, link, source, 'grounding', published)
                    if item and item['url'] not in {i['url'] for i in items}:
                        items.append(item)
                    if len(items) >= lim:
                        break
            except Exception:
                continue
    return items[:lim]


async def web_search(query, limit=5):
    q = ' '.join(str(query or '').split())[:300]
    lim = max(1, min(int(limit or 5), 8))
    if not q:
        return {'error': 'query_required'}
    url = 'https://duckduckgo.com/html/?q=' + quote_plus(q)
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers={'user-agent': 'Dirac/news web_search', 'accept': 'text/html'}) as client:
            resp = await client.get(url)
        text = resp.text[:200000]
    except Exception as e:
        return {'query': q, 'error': type(e).__name__}
    results = []
    for match in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.I | re.S):
        href = normalize_news_url(match.group(1))
        title = normalize_news_text(match.group(2))
        if href and title:
            results.append({'title': title[:220], 'url': href[:1000]})
        if len(results) >= lim:
            break
    return {'query': q, 'status_code': resp.status_code, 'results': results, 'truncated': len(results) >= lim}


def extract_date_from_text(text: Any) -> str | None:
    value = str(text or '')[:8000]
    patterns = [
        r'(?:article:published_time|datePublished)["\':\s=]+([^"<,\n]+)',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
        r'\b(20\d{2}-\d{2}-\d{2}(?:[T ][0-9:.+-]+Z?)?)\b',
        r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+20\d{2})\b',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, value, re.I):
            parsed = parse_news_date(match.group(1))
            if parsed:
                return parsed
    return None


async def fetch_exploratory_news(limit=EXPLORATORY_NEWS_LIMIT, *, fetcher=None):
    lim = max(1, int(limit or EXPLORATORY_NEWS_LIMIT))
    raw = []
    seen_urls = set()
    seen_titles = set()
    for query in EXPLORATORY_NEWS_QUERIES:
        result = await web_search(query, 5)
        for item in result.get('results') or []:
            title_key = normalize_news_key(item.get('title'))
            url = normalize_news_url(item.get('url'))
            if not title_key or not url or url in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(url)
            seen_titles.add(title_key)
            raw.append({'title': item.get('title'), 'url': url, 'query': query})
            if len(raw) >= 12:
                break
        if len(raw) >= 12:
            break
    items = []
    for candidate in raw[:6]:
        published = None
        status = None
        if fetcher is not None:
            try:
                fetched = await fetcher(candidate['url'], 'news exploration date/source check')
                status = fetched.get('status_code') if isinstance(fetched, dict) else None
                if isinstance(fetched, dict) and fetched.get('ok'):
                    published = extract_date_from_text(fetched.get('text') or '')
            except Exception:
                published = None
        item = news_item(
            candidate['title'],
            candidate['url'],
            urlparse(candidate['url']).netloc or 'web_search',
            'exploratory',
            published,
            {'query': candidate.get('query'), 'status_code': status},
        )
        if item:
            items.append(item)
        if len(items) >= lim:
            break
    return sorted(items, key=lambda item: {'fresh': 0, 'unknown': 1, 'older': 2}.get(item.get('date_status'), 3))[:lim]


async def fetch_ai_tech_news(limit=TECH_NEWS_MAX_ITEMS):
    return [{k: v for k, v in item.items() if k not in {'metadata'}} for item in await fetch_known_news(tech_news_limit(limit))]


async def upsert_news_item(db, item):
    now = utc_now()
    url = normalize_news_url(item.get('url') or item.get('link'))
    title = normalize_news_text(item.get('title'))
    source = normalize_news_text(item.get('source') or 'source')
    source_kind = item.get('source_kind') if item.get('source_kind') in {'grounding', 'exploratory'} else 'grounding'
    published = parse_news_date(item.get('published_at_utc'))
    metadata = dict(item.get('metadata') or {})
    metadata['date_status'] = item.get('date_status') or date_status(published)
    cur = await db.execute('SELECT first_seen_utc,last_posted_utc,posted_count FROM news_items WHERE url=?', (url,))
    row = await cur.fetchone()
    if row:
        await db.execute(
            'UPDATE news_items SET title=?,source=?,source_kind=?,published_at_utc=COALESCE(?,published_at_utc),last_seen_utc=?,metadata_json=? WHERE url=?',
            (title, source, source_kind, published, now, json.dumps(metadata, ensure_ascii=False, sort_keys=True), url),
        )
    else:
        await db.execute(
            'INSERT INTO news_items(url,title,source,source_kind,published_at_utc,first_seen_utc,last_seen_utc,last_posted_utc,posted_count,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (url, title, source, source_kind, published, now, now, None, 0, json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
        )
    await db.commit()
    return url


async def mark_news_items_posted(db, items):
    now = utc_now()
    for item in items:
        url = normalize_news_url(item.get('url') or item.get('link'))
        await db.execute('UPDATE news_items SET last_posted_utc=?,posted_count=posted_count+1 WHERE url=?', (now, url))
    await db.commit()


async def recent_posted_news(db, limit=30):
    cur = await db.execute(
        'SELECT url,title,source,source_kind,published_at_utc,last_posted_utc,posted_count,metadata_json FROM news_items WHERE last_posted_utc IS NOT NULL ORDER BY last_posted_utc DESC LIMIT ?',
        (max(1, int(limit or 30)),),
    )
    rows = await cur.fetchall()
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in rows]


async def _posted_map(db):
    cur = await db.execute('SELECT url,last_posted_utc,posted_count FROM news_items')
    rows = await cur.fetchall()
    return {row[0]: {'last_posted_utc': row[1], 'posted_count': row[2]} for row in rows}


def _recently_posted(last_posted_utc):
    if not last_posted_utc:
        return False
    try:
        posted = datetime.fromisoformat(str(last_posted_utc).replace('Z', '+00:00')).astimezone(timezone.utc)
    except Exception:
        return False
    return posted >= datetime.now(timezone.utc) - timedelta(hours=RECENT_POSTED_HOURS)


def _rank_candidates(items, posted):
    def score(item):
        state = posted.get(normalize_news_url(item.get('url') or item.get('link')), {})
        last_posted = state.get('last_posted_utc')
        if not last_posted:
            recency = 0
        elif not _recently_posted(last_posted):
            recency = 1
        else:
            recency = 2
        date_rank = {'fresh': 0, 'unknown': 1, 'older': 2}.get(item.get('date_status'), 3)
        return recency, date_rank, int(state.get('posted_count') or 0)
    return sorted(items, key=score)


def _fresh_or_repeat_fallback(items, posted):
    fresh = []
    repeated = []
    for item in items or []:
        state = posted.get(normalize_news_url(item.get('url') or item.get('link')), {})
        if _recently_posted(state.get('last_posted_utc')):
            repeated.append(item)
        else:
            fresh.append(item)
    return fresh if fresh else repeated


async def select_news_candidates(db, known_items, exploratory_items):
    posted = await _posted_map(db)
    known_pool = _fresh_or_repeat_fallback(list(known_items or []), posted)
    exploratory_pool = _fresh_or_repeat_fallback(list(exploratory_items or []), posted)
    known = _rank_candidates(known_pool, posted)[:KNOWN_NEWS_LIMIT]
    exploratory = _rank_candidates(exploratory_pool, posted)[:EXPLORATORY_NEWS_LIMIT]
    selected = known + exploratory
    repeating = bool(selected) and all(_recently_posted(posted.get(normalize_news_url(i.get('url') or i.get('link')), {}).get('last_posted_utc')) for i in selected)
    for item in selected:
        state = posted.get(normalize_news_url(item.get('url') or item.get('link')), {})
        item['recently_posted'] = _recently_posted(state.get('last_posted_utc'))
        item['posted_count'] = int(state.get('posted_count') or 0)
    return {'items': selected, 'repeating': repeating}


def _item_line(item):
    published = item.get('published_at_utc') or 'date_unknown'
    recent = ' recently_posted' if item.get('recently_posted') else ''
    return f"- [{item.get('source_kind')}/{item.get('source')}] {item.get('title')} ({item.get('url') or item.get('link')}) date={published} status={item.get('date_status') or 'unknown'}{recent}"


def build_news_prompt_payload(db, candidates, previous_items):
    items = list(candidates.get('items') if isinstance(candidates, dict) else candidates or [])
    repeating = bool(candidates.get('repeating')) if isinstance(candidates, dict) else False
    grounding = [item for item in items if item.get('source_kind') == 'grounding']
    exploratory = [item for item in items if item.get('source_kind') == 'exploratory']
    previous = list(previous_items or [])
    repeat_note = 'No fresh unseen items found; repeating latest known sources.' if repeating else ''
    grounding_text = '\n'.join(_item_line(item) for item in grounding) or '- none'
    exploratory_text = '\n'.join(_item_line(item) for item in exploratory) or '- none'
    previous_text = '\n'.join(f"- [{row.get('source_kind')}/{row.get('source')}] {row.get('title')} ({row.get('url')}) last_posted={row.get('last_posted_utc')}" for row in previous[:10]) or '- none'
    prompt = (
        (repeat_note + '\n\n' if repeat_note else '') +
        'Known-source grounding:\n' + grounding_text +
        '\n\nExploratory web-search candidates:\n' + exploratory_text +
        '\n\nRecently posted items to avoid repeating when possible:\n' + previous_text
    )
    fallback = 'Latest AI/model news:\n'
    if repeat_note:
        fallback += repeat_note + '\n'
    if grounding:
        fallback += '\nGrounding:\n' + grounding_text + '\n'
    if exploratory:
        fallback += '\nExploration:\n' + exploratory_text + '\n'
    return {'prompt': prompt, 'fallback': fallback.strip(), 'items': items, 'repeating': repeating}


def memory_note_for_summary(summary, items):
    rows = [
        {
            'title': item.get('title'),
            'source': item.get('source'),
            'source_kind': item.get('source_kind'),
            'url': item.get('url') or item.get('link'),
            'published_at_utc': item.get('published_at_utc') or 'date_unknown',
        }
        for item in items
    ]
    return (summary + '\n\nItems:\n' + json.dumps(rows, ensure_ascii=False, indent=2)).strip()
