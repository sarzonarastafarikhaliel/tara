"""
api_client.py – Wikipedia-based tourist spot fetcher for TARA.

Uses Wikipedia's MediaWiki API to search for tourism-related articles
in Philippine regions, then extracts coordinates, summaries, and
images.  No API key required – completely free and always available.
Results are cached in-memory (1-hour TTL).
"""

import requests
import time
import logging
import hashlib

logger = logging.getLogger(__name__)

# ── Wikipedia MediaWiki API ───────────────────────────────────────────
WIKI_API = 'https://en.wikipedia.org/w/api.php'
USER_AGENT = 'TARA-App/1.0 (tara-ph-travel@example.com)'

# Bounding boxes for Philippine island groups (lat_min, lat_max, lng_min, lng_max)
REGION_BOUNDS = {
    'luzon':    (12.0, 19.5, 116.5, 126.5),
    'visayas':  (9.0, 12.5, 121.5, 126.0),
    'mindanao': (5.5, 10.0, 121.5, 127.0),
}

# Search queries per TARA activity type – combined with region name
ACTIVITY_QUERIES = {
    'beach':     'beach OR island OR coast OR diving OR snorkeling OR resort',
    'hiking':    'mountain OR hiking OR trail OR volcano OR waterfall OR park OR nature',
    'city_tour': 'city OR landmark OR plaza OR park OR tourism',
    'culture':   'church OR museum OR heritage OR historic OR temple OR UNESCO OR cultural',
}

# Daily budget estimate strings (PHP)
BUDGET_ESTIMATES = {
    'budget':    '₱500-₱2,000/day',
    'mid-range': '₱2,000-₱6,000/day',
    'premium':   '₱6,000+/day',
}

# ── In-memory cache ───────────────────────────────────────────────────
_cache: dict = {}
CACHE_TTL = 3600  # seconds (1 hour)


def _cache_key(region: str, activity: str) -> str:
    raw = f'{region.lower()}:{activity.lower()}'
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(key: str):
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry['ts'] < CACHE_TTL:
            logger.info('Cache HIT  key=%s', key)
            return entry['data']
        del _cache[key]
    return None


def _set_cached(key: str, data):
    _cache[key] = {'data': data, 'ts': time.time()}


# ── Public API ─────────────────────────────────────────────────────────
def fetch_spots(region: str, activity: str) -> list[dict]:
    """
    Fetch tourist spots from Wikipedia for a given Philippine region
    and activity type.

    Parameters
    ----------
    region   : one of 'Luzon', 'Visayas', 'Mindanao'
    activity : one of 'beach', 'hiking', 'city_tour', 'culture'

    Returns
    -------
    list[dict]  –  spots in TARA format
    """
    region_key = region.lower()
    activity_key = activity.lower()

    # ── Check cache ───────────────────────────────────────────────────
    key = _cache_key(region_key, activity_key)
    cached = _get_cached(key)
    if cached is not None:
        return cached

    # ── Validate inputs ───────────────────────────────────────────────
    bounds = REGION_BOUNDS.get(region_key)
    activity_terms = ACTIVITY_QUERIES.get(activity_key)
    if not bounds or not activity_terms:
        logger.warning('Unknown region=%s or activity=%s', region, activity)
        return []

    # ── Call Wikipedia API ────────────────────────────────────────────
    search_query = f'({activity_terms}) {region} Philippines'
    params = {
        'action':      'query',
        'generator':   'search',
        'gsrsearch':   search_query,
        'gsrlimit':    50,
        'prop':        'coordinates|extracts|pageimages|categories',
        'exintro':     1,
        'explaintext': 1,
        'exlimit':     50,
        'piprop':      'thumbnail',
        'pithumbsize': 640,
        'cllimit':     10,
        'format':      'json',
    }

    try:
        resp = requests.get(
            WIKI_API,
            params=params,
            headers={'User-Agent': USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as e:
        logger.error('Wikipedia API error: %s', e)
        raise RuntimeError(f'Could not reach Wikipedia API: {e}')

    # ── Parse & filter results ────────────────────────────────────────
    pages = payload.get('query', {}).get('pages', {})
    spots = []
    idx = 0

    for page_id, page in pages.items():
        # Skip pages without coordinates
        coords = page.get('coordinates', [])
        if not coords:
            continue

        lat = coords[0].get('lat')
        lon = coords[0].get('lon')
        if lat is None or lon is None:
            continue

        # Filter: must be within the region's bounding box
        lat_min, lat_max, lng_min, lng_max = bounds
        if not (lat_min <= lat <= lat_max and lng_min <= lon <= lng_max):
            continue

        idx += 1
        spot = _parse_wiki_page(page, idx, region, activity_key, lat, lon)
        if spot:
            spots.append(spot)

    _set_cached(key, spots)
    logger.info('Fetched %d spots from Wikipedia  region=%s  activity=%s',
                len(spots), region, activity)
    return spots


# ── Budget estimation ──────────────────────────────────────────────────
def _estimate_budget(title: str, extract: str, categories: list, activity: str) -> str:
    """
    Estimate TARA budget tier from Wikipedia article content.

    Priority:
      1. Keyword heuristic on title + extract + categories
      2. Activity-level default
    """
    text = f'{title} {extract} {" ".join(categories)}'.lower()

    premium_kw = ['resort', 'luxury', 'spa', 'five-star', '5-star',
                  'exclusive', 'premier', 'golf', 'casino']
    midrange_kw = ['hotel', 'inn', 'lodge', 'villa', 'suites', 'boutique',
                   'world heritage', 'island hopping', 'whale shark',
                   'scuba', 'wreck diving']
    budget_kw = ['public', 'national park', 'trail', 'church', 'temple',
                 'museum', 'plaza', 'monument', 'memorial', 'free',
                 'park', 'market', 'basilica', 'fort', 'ruins']

    if any(kw in text for kw in premium_kw):
        return 'premium'
    if any(kw in text for kw in midrange_kw):
        return 'mid-range'
    if any(kw in text for kw in budget_kw):
        return 'budget'

    # Activity-level default
    return {
        'beach':     'mid-range',
        'hiking':    'budget',
        'city_tour': 'budget',
        'culture':   'budget',
    }.get(activity, 'mid-range')


# ── Highlight extraction ──────────────────────────────────────────────
def _extract_highlights(title: str, extract: str, categories: list, activity: str) -> list:
    """Extract highlight tags from Wikipedia article content."""
    text = f'{title} {extract}'.lower()
    highlights = []

    # Activity-specific keywords to look for
    keyword_map = {
        'beach':     [('Diving', 'diving'), ('Snorkeling', 'snorkel'),
                      ('White Sand', 'white sand'), ('Surfing', 'surf'),
                      ('Island', 'island'), ('Coral Reef', 'coral'),
                      ('Swimming', 'swimming'), ('Beach', 'beach')],
        'hiking':    [('Mountain', 'mountain'), ('Volcano', 'volcano'),
                      ('Waterfall', 'waterfall'), ('Trail', 'trail'),
                      ('Summit', 'summit'), ('Forest', 'forest'),
                      ('Trekking', 'trek'), ('Camping', 'camp')],
        'city_tour': [('Walking Tour', 'walking'), ('Market', 'market'),
                      ('Food', 'food'), ('Architecture', 'architect'),
                      ('Park', 'park'), ('Landmark', 'landmark'),
                      ('Shopping', 'shopping'), ('Plaza', 'plaza')],
        'culture':   [('UNESCO', 'unesco'), ('Heritage', 'heritage'),
                      ('Museum', 'museum'), ('Church', 'church'),
                      ('Colonial', 'colonial'), ('Historical', 'histor'),
                      ('Festival', 'festival'), ('Traditional', 'traditional')],
    }

    for label, keyword in keyword_map.get(activity, []):
        if keyword in text and label not in highlights:
            highlights.append(label)
        if len(highlights) >= 4:
            break

    # Fallback
    if not highlights:
        fallbacks = {
            'beach':     ['Beach', 'Coastal', 'Scenic'],
            'hiking':    ['Nature', 'Outdoor', 'Scenic'],
            'city_tour': ['Sightseeing', 'Landmark', 'Local'],
            'culture':   ['Heritage', 'History', 'Cultural'],
        }
        highlights = fallbacks.get(activity, ['Tourist Spot'])

    return highlights


# ── Page parser ────────────────────────────────────────────────────────
def _parse_wiki_page(page: dict, idx: int, region: str, activity: str,
                     lat: float, lon: float) -> dict | None:
    """Convert a Wikipedia page object into a TARA spot dict."""

    title = page.get('title', 'Unknown')
    extract = page.get('extract', '') or ''
    categories_raw = page.get('categories', [])
    cat_names = [c.get('title', '').replace('Category:', '') for c in categories_raw]

    # Build a clean description (truncate if too long)
    description = extract.strip()
    if len(description) > 300:
        # Cut at last sentence boundary before 300 chars
        cut = description[:300].rfind('.')
        if cut > 100:
            description = description[:cut + 1]
        else:
            description = description[:297] + '...'

    if not description:
        description = f'A popular {activity.replace("_", " ")} destination in {region.capitalize()}, Philippines.'

    # Estimate budget from content
    budget_level = _estimate_budget(title, extract, cat_names, activity)

    # Extract highlights from content
    highlights = _extract_highlights(title, extract, cat_names, activity)

    # Build tags for TF-IDF corpus
    tags = ' '.join([
        title,
        ' '.join(cat_names[:5]),
        region,
        'Philippines tourism travel',
        activity.replace('_', ' '),
    ])

    # Wikipedia title for photo lookup (already used by the /photo endpoint)
    wiki_title = title.replace(' ', '_')

    # Try to extract province/municipality from extract text
    province, municipality = _guess_location(title, extract, region)

    # Extract thumbnail if available
    thumbnail = page.get('thumbnail', {}).get('source', '')

    return {
        'id':               idx,
        'name':             title,
        'region':           region.capitalize(),
        'province':         province,
        'municipality':     municipality,
        'category':         activity,
        'budget_level':     budget_level,
        'description':      description,
        'tags':             tags,
        'lat':              lat,
        'lng':              lon,
        'wikimedia_title':  wiki_title,
        'image_url':        thumbnail,
        'estimated_budget': BUDGET_ESTIMATES.get(budget_level, '₱2,000-₱6,000/day'),
        'highlights':       highlights,
    }


# ── Location guesser ──────────────────────────────────────────────────
# Common Philippine provinces to look for in article text
_PH_PROVINCES = [
    'Palawan', 'Cebu', 'Bohol', 'Iloilo', 'Aklan', 'Leyte', 'Samar',
    'Negros Occidental', 'Negros Oriental', 'Batangas', 'Pangasinan',
    'Ilocos Norte', 'Ilocos Sur', 'Benguet', 'Ifugao', 'Albay',
    'Camarines Sur', 'Sorsogon', 'Zambales', 'Quezon', 'Laguna',
    'Pampanga', 'Bukidnon', 'Davao del Sur', 'Davao del Norte',
    'Davao Oriental', 'Surigao del Norte', 'Surigao del Sur',
    'South Cotabato', 'Misamis Oriental', 'Zamboanga del Sur',
    'Camiguin', 'Metro Manila', 'Cavite', 'Rizal',
]

_PH_CITIES = [
    'El Nido', 'Coron', 'Boracay', 'Cebu City', 'Tagbilaran',
    'Tacloban', 'Oslob', 'Moalboal', 'Bantayan', 'Malapascua',
    'Siargao', 'General Luna', 'Davao City', 'Cagayan de Oro',
    'Zamboanga City', 'General Santos', 'Vigan', 'Baguio',
    'Manila', 'Taguig', 'Makati', 'Legazpi', 'Pagudpud',
    'Caramoan', 'Donsol', 'Puerto Galera', 'San Juan',
    'Mati', 'Bislig', 'Hinatuan', 'Mambajao',
]


def _guess_location(title: str, extract: str, region: str) -> tuple[str, str]:
    """Try to guess province and municipality from article text."""
    text = f'{title} {extract}'
    province = ''
    municipality = ''

    for prov in _PH_PROVINCES:
        if prov in text:
            province = prov
            break

    for city in _PH_CITIES:
        if city in text:
            municipality = city
            break

    return province, municipality
