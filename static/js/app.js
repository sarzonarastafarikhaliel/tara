/* ================================================================
   TARA — app.js
   Frontend logic: form handling, card rendering, Leaflet map
   ================================================================ */

'use strict';

// ── State ──────────────────────────────────────────────────────────
const state = {
  region:   null,
  budget:   null,
  activity: null,
  results:  [],
  map:      null,
  markers:  [],
  activeCard: null,
};

// Category icons for map markers & placeholders
const CATEGORY_EMOJI = {
  beach:     '🏖️',
  hiking:    '🥾',
  city_tour: '🏙️',
  culture:   '🏛️',
};
const CATEGORY_COLOR = {
  beach:     '#3B82F6',
  hiking:    '#10B981',
  city_tour: '#8B5CF6',
  culture:   '#F59E0B',
};

// ── DOM Refs ───────────────────────────────────────────────────────
const form         = document.getElementById('preferenceForm');
const submitBtn    = document.getElementById('submitBtn');
const btnLabel     = submitBtn.querySelector('.btn-label');
const btnSpinner   = submitBtn.querySelector('.btn-spinner');
const btnIcon      = submitBtn.querySelector('.btn-icon');
const formError    = document.getElementById('formError');
const resultsSection = document.getElementById('results-section');
const resultsContainer = document.getElementById('resultsContainer');
const resultsSubtitle  = document.getElementById('resultsSubtitle');
const noResults        = document.getElementById('noResults');
const prefPills        = document.getElementById('prefPills');
const navMapLink       = document.getElementById('navMapLink');
const navbar           = document.getElementById('navbar');
const sumRegion        = document.getElementById('sumRegion');
const sumBudget        = document.getElementById('sumBudget');
const sumActivity      = document.getElementById('sumActivity');

// ── Navbar scroll effect ───────────────────────────────────────────
window.addEventListener('scroll', () => {
  navbar.classList.toggle('scrolled', window.scrollY > 30);
}, { passive: true });

// ── Option Card Selection ──────────────────────────────────────────
document.querySelectorAll('.option-card').forEach(card => {
  card.addEventListener('click', () => {
    const field = card.dataset.field;
    const value = card.dataset.value;

    // Deselect siblings
    document.querySelectorAll(`.option-card[data-field="${field}"]`).forEach(c => {
      c.classList.remove('selected');
      c.setAttribute('aria-pressed', 'false');
    });

    // Select this card
    card.classList.add('selected');
    card.setAttribute('aria-pressed', 'true');
    state[field] = value;

    // HCI: update live selection summary
    updateSummary();
    hideError();
  });
});

// ── Selection Summary (HCI: Visibility of system status) ──────────
const SUMMARY_IDS = { region: 'sumRegion', budget: 'sumBudget', activity: 'sumActivity' };
const SUMMARY_LABELS = {
  region:   { Luzon: 'Luzon', Visayas: 'Visayas', Mindanao: 'Mindanao' },
  budget:   { budget: 'Budget', 'mid-range': 'Mid-range', premium: 'Premium' },
  activity: { beach: 'Beach', hiking: 'Hiking', city_tour: 'City Tour', culture: 'Culture' },
};

function updateSummary() {
  for (const [field, elId] of Object.entries(SUMMARY_IDS)) {
    const el = document.getElementById(elId);
    const label = el.querySelector('.sum-label');
    const val = state[field];
    if (val) {
      label.textContent = SUMMARY_LABELS[field][val] || val;
      el.classList.add('done');
    } else {
      label.textContent = 'not set';
      el.classList.remove('done');
    }
  }

  // HCI: button becomes active only when all 3 are selected
  const ready = state.region && state.budget && state.activity;
  submitBtn.disabled = !ready;
  if (ready) {
    submitBtn.classList.add('ready');
    submitBtn.classList.remove('loading');
    btnLabel.textContent = 'Get recommendations';
    btnIcon.textContent = '→';
  } else {
    submitBtn.classList.remove('ready');
    btnLabel.textContent = 'Select region, budget & activity to continue';
    btnIcon.textContent = '';
  }
}

// ── Form Submission ────────────────────────────────────────────────
form.addEventListener('submit', async (e) => {
  e.preventDefault();

  // Validate
  if (!state.region)   return showError('Please select a region.');
  if (!state.budget)   return showError('Please select a budget level.');
  if (!state.activity) return showError('Please select an activity type.');

  setLoading(true);
  hideError();

  try {
    const resp = await fetch('/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        region:   state.region,
        budget:   state.budget,
        activity: state.activity,
      }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `Server error ${resp.status}`);
    }

    const data = await resp.json();
    state.results = data.results || [];
    renderResults();

  } catch (err) {
    showError(`Something went wrong: ${err.message}`);
  } finally {
    setLoading(false);
  }
});

// ── Render Results ─────────────────────────────────────────────────
function renderResults() {
  const { results, region, budget, activity } = state;

  // Show section
  resultsSection.style.display = '';
  navMapLink.style.display = '';

  // Update subtitle
  resultsSubtitle.textContent = `Showing ${results.length} spot${results.length !== 1 ? 's' : ''} in ${region}`;

  // Preference pills
  prefPills.innerHTML = `
    <span class="pref-pill region">📍 ${region}</span>
    <span class="pref-pill budget">${budgetLabel(budget)}</span>
    <span class="pref-pill activity">${activityLabel(activity)}</span>
  `;

  // No results state
  if (results.length === 0) {
    resultsContainer.innerHTML = '';
    noResults.style.display = '';
    clearMap();
    scrollToResults();
    return;
  }
  noResults.style.display = 'none';

  // Render cards
  resultsContainer.innerHTML = '';
  results.forEach((spot, idx) => {
    const card = buildCard(spot, idx);
    resultsContainer.appendChild(card);
  });

  // Init / update map
  renderMap(results);
  scrollToResults();
}

// ── Build Spot Card ────────────────────────────────────────────────
function buildCard(spot, idx) {
  const div = document.createElement('div');
  div.className = 'spot-card';
  div.dataset.id = spot.id;
  div.setAttribute('role', 'article');
  div.setAttribute('aria-label', spot.name);
  div.style.animationDelay = `${idx * 0.06}s`;

  const emoji = CATEGORY_EMOJI[spot.category] || '📍';
  const score = spot.match_score != null ? `${Math.round(spot.match_score)}%` : '';
  const location = [spot.municipality, spot.province].filter(Boolean).join(', ');
  const highlights = Array.isArray(spot.highlights)
    ? spot.highlights.slice(0, 2).join(' · ')
    : '';

  div.innerHTML = `
    <div class="card-img-wrap">
      <div class="card-img-placeholder" id="placeholder-${spot.id}">${emoji}</div>
    </div>
    <div class="card-body">
      <div class="card-row-top">
        <div class="card-name">${escHtml(spot.name)}</div>
        ${score ? `<div class="match-badge">${score}</div>` : ''}
      </div>
      <div class="card-location">📍 ${escHtml(location)}</div>
      <div class="card-desc">${escHtml(spot.description)}</div>
      <div class="card-footer">
        <div class="card-budget">💰 ${escHtml(spot.estimated_budget || '')}</div>
        <div class="card-category">${activityLabel(spot.category)}</div>
      </div>
    </div>
    <div class="rank-badge" aria-label="Rank ${idx + 1}">${idx + 1}</div>
  `;

  // Click: fly map to spot
  div.addEventListener('click', () => activateCard(div, spot, idx));

  // Lazy-load photo
  loadPhoto(spot, div);

  return div;
}

// ── Load Wikipedia Photo ───────────────────────────────────────────
async function loadPhoto(spot, cardEl) {
  if (!spot.wikimedia_title) return;
  try {
    const resp = await fetch(`/photo?title=${encodeURIComponent(spot.wikimedia_title)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.url) {
      const wrap = cardEl.querySelector('.card-img-wrap');
      const placeholder = wrap.querySelector('.card-img-placeholder');
      const img = document.createElement('img');
      img.className = 'card-img';
      img.setAttribute('alt', spot.name);
      img.setAttribute('loading', 'lazy');
      img.onload = () => {
        placeholder.style.display = 'none';
        wrap.appendChild(img);
      };
      img.onerror = () => {};
      img.src = data.url;
    }
  } catch (_) {}
}

// ── Activate Card (highlight + fly map) ───────────────────────────
function activateCard(cardEl, spot, idx) {
  // Deactivate previous
  if (state.activeCard) state.activeCard.classList.remove('active');
  cardEl.classList.add('active');
  state.activeCard = cardEl;

  // Fly map
  if (state.map && spot.lat && spot.lng) {
    state.map.flyTo([spot.lat, spot.lng], 13, { duration: 1.2 });
    const marker = state.markers[idx];
    if (marker) marker.openPopup();
  }
}

// ── Leaflet Map ────────────────────────────────────────────────────
function renderMap(spots) {
  if (!state.map) {
    state.map = L.map('map', {
      zoomControl: true,
      attributionControl: true,
    });

    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      {
        attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a> © <a href="https://carto.com">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
      }
    ).addTo(state.map);
  }

  clearMap();

  const validSpots = spots.filter(s => s.lat && s.lng);
  if (validSpots.length === 0) return;

  validSpots.forEach((spot, idx) => {
    const color = CATEGORY_COLOR[spot.category] || '#F59E0B';
    const emoji = CATEGORY_EMOJI[spot.category] || '📍';
    const score = spot.match_score != null ? Math.round(spot.match_score) : '';
    const location = [spot.municipality, spot.province].filter(Boolean).join(', ');

    // Custom SVG icon
    const icon = L.divIcon({
      className: '',
      html: `
        <div style="
          width:36px;height:36px;border-radius:50% 50% 50% 0;
          background:${color};
          border:2px solid rgba(255,255,255,0.2);
          box-shadow:0 3px 12px rgba(0,0,0,0.5);
          display:flex;align-items:center;justify-content:center;
          font-size:16px;transform:rotate(-45deg);cursor:pointer;
          transition:transform 0.2s;
        ">
          <span style="transform:rotate(45deg)">${emoji}</span>
        </div>`,
      iconSize: [36, 36],
      iconAnchor: [18, 36],
      popupAnchor: [0, -38],
    });

    const marker = L.marker([spot.lat, spot.lng], { icon })
      .addTo(state.map)
      .bindPopup(`
        <div class="map-popup">
          <div class="map-popup-name">${escHtml(spot.name)}</div>
          <div class="map-popup-loc">📍 ${escHtml(location)}</div>
          ${score ? `<span class="map-popup-score">⭐ ${score}% match</span>` : ''}
        </div>
      `, { maxWidth: 240 });

    // Clicking a marker activates the corresponding card
    marker.on('click', () => {
      const cardEl = resultsContainer.querySelector(`.spot-card[data-id="${spot.id}"]`);
      if (cardEl) {
        activateCard(cardEl, spot, idx);
        cardEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });

    state.markers.push(marker);
  });

  // Fit map to all markers
  const group = L.featureGroup(state.markers);
  state.map.fitBounds(group.getBounds().pad(0.15));
}

function clearMap() {
  state.markers.forEach(m => m.remove());
  state.markers = [];
}

// ── Helpers ────────────────────────────────────────────────────────
function setLoading(on) {
  submitBtn.disabled = on;
  if (on) {
    submitBtn.classList.add('loading');
    submitBtn.classList.remove('ready');
    btnLabel.style.display = 'none';
    btnIcon.style.display  = 'none';
    btnSpinner.style.display = '';
  } else {
    submitBtn.classList.remove('loading');
    btnLabel.style.display = '';
    btnIcon.style.display  = '';
    btnSpinner.style.display = 'none';
    updateSummary(); // restore correct button state
  }
}

function showError(msg) {
  formError.textContent = msg;
  formError.style.display = '';
  formError.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideError() {
  formError.style.display = 'none';
}

function scrollToResults() {
  setTimeout(() => {
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 150);
}

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function budgetLabel(b) {
  return { budget: 'Budget', 'mid-range': 'Mid-range', premium: 'Premium' }[b] || b;
}

function activityLabel(a) {
  return {
    beach:     'Beach & Island',
    hiking:    'Hiking & Nature',
    city_tour: 'City Tour',
    culture:   'Heritage & Culture',
  }[a] || a;
}
