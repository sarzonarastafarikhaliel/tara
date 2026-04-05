from flask import Flask, render_template, request, jsonify, send_from_directory
import requests as http_requests
import logging
import os

from recommender import get_recommendations

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VALID_REGIONS   = {'luzon', 'visayas', 'mindanao'}
VALID_BUDGETS   = {'budget', 'mid-range', 'premium'}
VALID_ACTIVITIES = {'beach', 'hiking', 'city_tour', 'culture'}

WIKIPEDIA_API = 'https://en.wikipedia.org/api/rest_v1/page/summary/{}'


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/recommend', methods=['POST'])
def recommend():
    data = request.get_json(silent=True) or {}

    region   = str(data.get('region', '')).strip()
    budget   = str(data.get('budget', '')).strip()
    activity = str(data.get('activity', '')).strip()

    # Input validation
    if region.lower() not in VALID_REGIONS:
        return jsonify({'error': 'Invalid region'}), 400
    if budget.lower() not in VALID_BUDGETS:
        return jsonify({'error': 'Invalid budget'}), 400
    if activity.lower() not in VALID_ACTIVITIES:
        return jsonify({'error': 'Invalid activity'}), 400

    try:
        results = get_recommendations(
            region=region.capitalize(),
            budget=budget.lower(),
            activity=activity.lower(),
            top_n=8
        )
        return jsonify({'results': results, 'count': len(results)})
    except Exception as e:
        app.logger.error(f'Recommendation error: {e}')
        return jsonify({'error': 'Could not generate recommendations'}), 500


@app.route('/photo')
def get_photo():
    """
    Proxy endpoint for Wikipedia page summary API.
    Returns the thumbnail URL for a given wikipedia article title.
    Avoids CORS issues from the browser when calling Wikipedia directly.
    """
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({'url': '', 'title': ''})

    try:
        resp = http_requests.get(
            WIKIPEDIA_API.format(title),
            timeout=6,
            headers={'User-Agent': 'TARA-App/1.0 (tara-ph-travel@example.com)'}
        )
        if resp.ok:
            payload = resp.json()
            thumbnail = payload.get('thumbnail', {})
            image_url = thumbnail.get('source', '')
            # Upgrade to larger thumbnail if we have a URL
            if image_url:
                image_url = image_url.replace('/320px-', '/640px-')
            return jsonify({'url': image_url, 'title': payload.get('title', title)})
    except Exception as e:
        app.logger.warning(f'Photo fetch failed for {title}: {e}')

    return jsonify({'url': '', 'title': title})


@app.route('/wbs')
def wbs():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'wbs.html')


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'app': 'TARA'})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
