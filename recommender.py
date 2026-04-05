import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from data_loader import load_spots

# Budget hierarchy for soft filtering
BUDGET_RANK = {'budget': 0, 'mid-range': 1, 'premium': 2}

# Keyword boosters that enrich the user query for better TF-IDF matching
ACTIVITY_KEYWORDS = {
    'beach':     'beach island sand sea swimming snorkeling diving ocean coral reef coastline waves surf',
    'hiking':    'mountain hike trekking trail summit camping forest nature outdoor altitude scenic',
    'city_tour': 'city urban culture food dining walking market heritage colonial nightlife architecture',
    'culture':   'heritage history culture colonial church museum traditions indigenous festival heritage art'
}


def get_recommendations(region: str, budget: str, activity: str, top_n: int = 8) -> list:
    """
    Two-step recommendation:
     1. Rule-based  – filter by exact region + activity match, soft budget cap
     2. Content-based – TF-IDF cosine similarity ranking of remaining spots
    """
    df = load_spots()

    # ── Step 1: Rule-based filtering ─────────────────────────────────────────
    filtered = df[
        (df['region'].str.lower() == region.lower()) &
        (df['category'].str.lower() == activity.lower())
    ].copy()

    user_budget_rank = BUDGET_RANK.get(budget.lower(), 1)

    # Soft budget filter: show spots at or below the user's level
    budget_filtered = filtered[
        filtered['budget_level'].apply(
            lambda b: BUDGET_RANK.get(b.lower(), 1) <= user_budget_rank
        )
    ]

    # Fall back to full activity-region set if budget filter leaves < 3 results
    if len(budget_filtered) >= 3:
        filtered = budget_filtered
    # else: keep all matched region+activity spots (budget relaxed)

    if filtered.empty:
        return []

    # ── Step 2: TF-IDF cosine similarity ranking ──────────────────────────────
    activity_boost = ACTIVITY_KEYWORDS.get(activity.lower(), '')
    user_query = f"{region} {activity} {budget} Philippines travel tourism {activity_boost}"

    corpus = filtered['corpus'].tolist()
    corpus_with_query = corpus + [user_query]

    vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2), min_df=1)
    tfidf_matrix = vectorizer.fit_transform(corpus_with_query)

    # Cosine similarity: query vector vs every spot vector
    query_vec = tfidf_matrix[-1]
    spot_vecs = tfidf_matrix[:-1]
    similarities = cosine_similarity(query_vec, spot_vecs)[0]

    filtered = filtered.copy()
    filtered['score'] = similarities

    # Normalise score to 0–100
    max_score = filtered['score'].max()
    if max_score > 0:
        filtered['match_score'] = (filtered['score'] / max_score * 100).round(1)
    else:
        filtered['match_score'] = 100.0

    result = (
        filtered
        .sort_values('score', ascending=False)
        .head(top_n)
    )

    # Return serialisable dicts (drop internal columns)
    cols = [
        'id', 'name', 'region', 'province', 'municipality', 'category',
        'budget_level', 'description', 'estimated_budget',
        'lat', 'lng', 'wikimedia_title', 'highlights', 'match_score'
    ]
    cols = [c for c in cols if c in result.columns]
    return result[cols].to_dict('records')
