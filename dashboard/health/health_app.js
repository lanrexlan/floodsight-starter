'use strict';

/**
 * FloodSight Health Intelligence Dashboard
 *
 * Reads from:
 *   /health/risk          — LGA outbreak probability scores
 *   /health/mel/summary   — KPI aggregates
 *   Supabase REST API     — DHIS2 cases + CHEW responses + MEL events
 *
 * Set SUPABASE_URL and SUPABASE_ANON_KEY below after deployment.
 * The anon/public key is safe to embed — Supabase RLS ensures health_alerts
 * and chew_subscribers (sensitive tables) require service_role.
 */

// ---------------------------------------------------------------------------
// Configuration — fill these in after Supabase project is set up
// ---------------------------------------------------------------------------
const SUPABASE_URL      = 'https://buwwsplrhsfgnkulhkpc.supabase.co';   // e.g. 'https://abcdefgh.supabase.co'
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ1d3dzcGxyaHNmZ25rdWxoa3BjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI5NDY0NDAsImV4cCI6MjA5ODUyMjQ0MH0.VjPpQ702fz83afiNbVDDfyao-fUbLbV6v3VpqwySKJQ';   // Settings → API → anon (public) key

// API base auto-detects local dev vs. Render deployment (same as existing app.js)
const API_BASE = location.protocol === 'file:'
  ? 'http://localhost:8000'
  : (location.hostname === 'localhost' ? 'http://localhost:8000' : '');

// MEL trial arms
const TREATMENT_LGAS = new Set(['Alimosho','Ajeromi-Ifelodun','Kosofe','Oshodi-Isolo','Ikorodu']);
const CONTROL_LGAS   = new Set(['Agege','Mushin','Surulere','Lagos Mainland','Ikeja']);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let casesChart = null;

async function apiFetch(path) {
  const r = await fetch(API_BASE + path);
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`);
  return r.json();
}

async function supabaseFetch(table, params = '') {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return [];
  const url = `${SUPABASE_URL}/rest/v1/${table}?${params}`;
  const r = await fetch(url, {
    headers: {
      'apikey':        SUPABASE_ANON_KEY,
      'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
      'Accept':        'application/json',
    }
  });
  if (!r.ok) {
    console.warn(`Supabase ${table} → HTTP ${r.status}`);
    return [];
  }
  return r.json();
}

function tierBadge(tier) {
  return `<span class="badge-tier tier-${tier}">${tier}</span>`;
}

function probBar(prob) {
  const pct = Math.round(prob * 100);
  let fillClass = '';
  if (pct >= 75) fillClass = 'critical';
  else if (pct >= 55) fillClass = 'high';
  return `
    <div class="prob-wrap">
      <span class="prob-pct">${pct}%</span>
      <div class="prob-bar">
        <div class="prob-fill ${fillClass}" style="width:${pct}%"></div>
      </div>
    </div>`;
}

function armPill(lgaName) {
  if (TREATMENT_LGAS.has(lgaName))
    return `<span class="arm-pill arm-treatment">Treatment</span>`;
  if (CONTROL_LGAS.has(lgaName))
    return `<span class="arm-pill arm-control">Control</span>`;
  return '';
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-NG', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'
  });
}

function fmtDateShort(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-NG', { day: 'numeric', month: 'short' });
}

// ---------------------------------------------------------------------------
// KPI cards
// ---------------------------------------------------------------------------

async function loadKPIs() {
  try {
    const data = await apiFetch('/health/mel/summary');
    document.getElementById('kpi-alerts').textContent  = (data.total_alerts_sent || 0).toLocaleString();
    document.getElementById('kpi-confirm').textContent = `${Math.round((data.chew_confirm_rate || 0) * 100)}%`;
    document.getElementById('kpi-mel').textContent     = (data.mel_events_logged || 0).toLocaleString();
    document.getElementById('kpi-nets').textContent    = (data.nets_distributed || 0).toLocaleString();
    document.getElementById('kpi-rdt').textContent     = (data.rdt_kits_prepositioned || 0).toLocaleString();
  } catch (e) {
    console.warn('KPI load failed:', e.message);
  }
}

// ---------------------------------------------------------------------------
// Outbreak risk table
// ---------------------------------------------------------------------------

async function loadRiskTable() {
  const container = document.getElementById('risk-table-container');
  const badge     = document.getElementById('risk-badge');

  try {
    const data = await apiFetch('/health/risk');
    const lgas = data.lgas || [];

    badge.textContent = `${lgas.length} LGAs scored`;
    document.getElementById('last-updated').textContent =
      data.computed_at ? new Date(data.computed_at).toLocaleString('en-NG') : 'Today';

    if (!lgas.length) {
      container.innerHTML = `<p class="state-msg">
        No outbreak risk scores for today — no active flood alerts in pilot LGAs.
        Risk scores appear when at least one LGA reaches Watch or Warning level.
      </p>`;
      return;
    }

    const rows = lgas.map(lga => {
      const alertDot = lga.alert_sent
        ? `<span class="dot dot-sent"></span>Sent`
        : `<span class="dot dot-pending"></span>Pending`;
      return `<tr>
        <td><strong>${lga.lga_name}</strong> ${armPill(lga.lga_name)}</td>
        <td>${tierBadge(lga.risk_tier)}</td>
        <td>${probBar(lga.outbreak_probability)}</td>
        <td>${(lga.inundation_area_km2 || 0).toFixed(2)} km²</td>
        <td>${lga.breeding_lag_days || '—'} days</td>
        <td style="font-size:.78rem;color:var(--muted)">
          ${fmtDateShort(lga.outbreak_window_start)}–${fmtDateShort(lga.outbreak_window_end)}
        </td>
        <td style="font-size:.78rem">${alertDot}</td>
      </tr>`;
    }).join('');

    container.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>LGA</th>
            <th>Risk Tier</th>
            <th>Probability</th>
            <th>Flood Area</th>
            <th>Breeding Lag</th>
            <th>Outbreak Window</th>
            <th>Alert</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;

  } catch (e) {
    badge.textContent = 'error';
    container.innerHTML = `<p class="state-msg" style="color:var(--red)">Error: ${e.message}</p>`;
  }
}

// ---------------------------------------------------------------------------
// DHIS2 cases chart (treatment vs. control)
// ---------------------------------------------------------------------------

async function loadCasesChart() {
  try {
    const rows = await supabaseFetch(
      'dhis2_malaria_cases',
      'select=lga_name,period,confirmed_cases&order=period.asc&limit=300'
    );

    if (!rows.length) {
      const ctx = document.getElementById('cases-chart').getContext('2d');
      ctx.font = '13px Segoe UI';
      ctx.fillStyle = '#94a3b8';
      ctx.fillText('No DHIS2 data yet — run scripts/mel_dhis2_pull.py to populate.', 10, 60);
      return;
    }

    const periods       = [...new Set(rows.map(r => r.period))].sort();
    const treatmentData = periods.map(p =>
      rows.filter(r => r.period === p && TREATMENT_LGAS.has(r.lga_name))
          .reduce((s, r) => s + (r.confirmed_cases || 0), 0)
    );
    const controlData = periods.map(p =>
      rows.filter(r => r.period === p && CONTROL_LGAS.has(r.lga_name))
          .reduce((s, r) => s + (r.confirmed_cases || 0), 0)
    );

    const ctx = document.getElementById('cases-chart').getContext('2d');
    if (casesChart) casesChart.destroy();

    casesChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: periods,
        datasets: [
          {
            label: 'Treatment LGAs',
            data: treatmentData,
            borderColor: '#00897b',
            backgroundColor: 'rgba(0,137,123,.12)',
            tension: 0.35, fill: true, pointRadius: 4,
          },
          {
            label: 'Control LGAs',
            data: controlData,
            borderColor: '#94a3b8',
            backgroundColor: 'rgba(148,163,184,.08)',
            borderDash: [5, 4],
            tension: 0.35, fill: true, pointRadius: 3,
          },
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y} confirmed cases`
            }
          }
        },
        scales: {
          x: {
            title: { display: true, text: 'Reporting Period', font: { size: 11 } },
            ticks: { font: { size: 10 } },
          },
          y: {
            title: { display: true, text: 'Confirmed Malaria Cases', font: { size: 11 } },
            beginAtZero: true,
            ticks: { font: { size: 10 } },
          }
        }
      }
    });
  } catch (e) {
    console.warn('Cases chart error:', e.message);
  }
}

// ---------------------------------------------------------------------------
// CHEW activity feed
// ---------------------------------------------------------------------------

const ACTION_ICONS = { CONFIRM: '✅', REPORT: '📊', HELP: '🆘', UNKNOWN: '❓' };
const ACTION_LABELS = {
  CONFIRM: 'Confirmed action',
  REPORT:  'Cases reported',
  HELP:    'Requested help',
  UNKNOWN: 'Unknown reply',
};

async function loadChewActivity() {
  const container = document.getElementById('chew-activity');
  try {
    const rows = await supabaseFetch(
      'chew_responses',
      'select=phone,parsed_action,cases_reported,lga_name,received_at&order=received_at.desc&limit=8'
    );

    if (!rows.length) {
      container.innerHTML = `<p class="state-msg">
        No CHEW responses yet. Responses appear here after CHEWs reply to alerts.
      </p>`;
      return;
    }

    const items = rows.map(r => {
      const icon   = ACTION_ICONS[r.parsed_action] || '❓';
      const label  = ACTION_LABELS[r.parsed_action] || 'Unknown';
      const phone  = r.phone ? ('*'.repeat(r.phone.length - 4) + r.phone.slice(-4)) : 'Unknown';
      const cases  = r.cases_reported != null ? ` · ${r.cases_reported} cases` : '';
      const lga    = r.lga_name || 'Unknown LGA';
      return `
        <div class="activity-item">
          <span class="activity-icon">${icon}</span>
          <div class="activity-body">
            <div class="activity-title">${label}${cases}</div>
            <div class="activity-meta">${phone} · ${lga} · ${fmtDate(r.received_at)}</div>
          </div>
        </div>`;
    }).join('');

    container.innerHTML = `<div class="activity-list">${items}</div>`;
  } catch (e) {
    container.innerHTML = `<p class="state-msg" style="color:var(--red)">Error: ${e.message}</p>`;
  }
}

// ---------------------------------------------------------------------------
// MEL events table
// ---------------------------------------------------------------------------

const MEL_ICONS = {
  NETS_DISTRIBUTED:         '🛏',
  RDT_KITS_PREPOSITIONED:   '🧪',
  IRS_CONDUCTED:            '🏠',
  COMMUNITY_SENSITIZATION:  '📢',
  CASE_MANAGEMENT_TRAINING: '📚',
  STOCK_PREPOSITIONING:     '📦',
};

async function loadMelTable() {
  const container = document.getElementById('mel-table-container');
  const badge     = document.getElementById('mel-badge');
  try {
    const rows = await supabaseFetch(
      'mel_events',
      'select=lga_name,event_type,quantity,unit,reported_by,event_date,facility_name&order=event_date.desc&limit=20'
    );

    badge.textContent = `${rows.length} recent events`;

    if (!rows.length) {
      container.innerHTML = `<p class="state-msg">
        No MEL events logged yet. CHEWs report actions via SMS (REPORT N) or
        via the MEL data entry form.
      </p>`;
      return;
    }

    const trows = rows.map(r => {
      const icon  = MEL_ICONS[r.event_type] || '📋';
      const label = r.event_type.replace(/_/g, ' ');
      const qty   = r.quantity != null ? `${r.quantity} ${r.unit || ''}`.trim() : '—';
      return `<tr>
        <td>${r.event_date || '—'}</td>
        <td>${armPill(r.lga_name)} ${r.lga_name}</td>
        <td>${icon} ${label}</td>
        <td>${qty}</td>
        <td style="font-size:.78rem;color:var(--muted)">${r.facility_name || '—'}</td>
      </tr>`;
    }).join('');

    container.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Date</th><th>LGA</th><th>Action</th><th>Quantity</th><th>Facility</th>
          </tr>
        </thead>
        <tbody>${trows}</tbody>
      </table>`;
  } catch (e) {
    badge.textContent = 'error';
    container.innerHTML = `<p class="state-msg" style="color:var(--red)">Error: ${e.message}</p>`;
  }
}

// ---------------------------------------------------------------------------
// Load all
// ---------------------------------------------------------------------------

async function loadAll() {
  document.getElementById('last-updated').textContent = 'Refreshing…';
  await Promise.allSettled([
    loadKPIs(),
    loadRiskTable(),
    loadCasesChart(),
    loadChewActivity(),
    loadMelTable(),
  ]);
}

// Boot
loadAll();

// Auto-refresh every 5 minutes
setInterval(loadAll, 5 * 60 * 1000);
