import json
import pandas as pd
import os

_spots_cache = None


def load_spots():
    """Load spots from JSON file with caching."""
    global _spots_cache
    if _spots_cache is not None:
        return _spots_cache.copy()

    data_path = os.path.join(os.path.dirname(__file__), 'data', 'spots.json')
    with open(data_path, 'r', encoding='utf-8') as f:
        spots = json.load(f)

    df = pd.DataFrame(spots)

    # Ensure required columns are strings
    for col in ['region', 'category', 'budget_level', 'tags', 'description']:
        if col in df.columns:
            df[col] = df[col].fillna('').astype(str)

    # Build a rich text corpus for TF-IDF (tags + description + name + province)
    df['corpus'] = (
        df['tags'] + ' ' +
        df['description'] + ' ' +
        df['name'] + ' ' +
        df.get('province', '') + ' ' +
        df.get('municipality', '')
    )

    _spots_cache = df
    return _spots_cache.copy()
