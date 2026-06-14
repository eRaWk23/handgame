import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';

const supabaseUrl = 'https://atorftwulkabkmhaeeir.supabase.co';
const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF0b3JmdHd1bGthYmttaGFlZWlyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzkwNDk5MTQsImV4cCI6MjA5NDYyNTkxNH0.SW0OdvAZvAh81PqpLkez1MO8WnMruQxMoCitpcd-PMs';
const supabase = createClient(supabaseUrl, supabaseKey);

// ─── State ───────────────────────────────────────────────
let currentPage = 1;
const eventsPerPage = 3;
const REPORT_THRESHOLD = 3;

const eventList = document.getElementById("event-list");
const searchInput = document.getElementById("search");
const togglePastBtn = document.getElementById("toggle-past");
const calendarContainer = document.getElementById("calendar-container");

const viewListBtn = document.getElementById("view-list");
const viewCalendarBtn = document.getElementById("view-calendar");

let allEvents = [];
let pastEvents = [];
let showingPast = false;
let currentView = 'list';
let calendarDate = new Date();

// ─── Report tracking (localStorage) ─────────────────────
function getReportedIds() {
  try { return JSON.parse(localStorage.getItem('reported_events') || '[]'); }
  catch { return []; }
}
function markReported(id) {
  const reported = getReportedIds();
  if (!reported.includes(id)) {
    reported.push(id);
    localStorage.setItem('reported_events', JSON.stringify(reported));
  }
}
function hasReported(id) {
  return getReportedIds().includes(id);
}

// ─── Data Loading ────────────────────────────────────────
async function loadEvents() {
  const { data, error } = await supabase
    .from('events')
    .select('*')
    .order('start_date', { ascending: true });

  if (error) {
    console.error('Error fetching events:', error);
    eventList.innerHTML = '<p style="text-align:center; color:#aaa;">Unable to load events right now. Try again later.</p>';
    return;
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const visible = data.filter(event => (event.report_count || 0) < REPORT_THRESHOLD);

  allEvents = visible.filter(event => new Date(event.start_date) >= today);
  pastEvents = visible.filter(event => new Date(event.start_date) < today).reverse();

  refresh();
}

// ─── Filtering ───────────────────────────────────────────
function getActiveEvents() {
  return showingPast ? pastEvents : allEvents;
}

function getFilteredEvents() {
  let events = getActiveEvents();
  const query = searchInput.value.toLowerCase();

  if (query) {
    events = events.filter(event =>
      (event.title    || "").toLowerCase().includes(query) ||
      (event.location || "").toLowerCase().includes(query) ||
      (event.tribe    || "").toLowerCase().includes(query) ||
      (event.details  || "").toLowerCase().includes(query)
    );
  }

  return events;
}

function refresh() {
  const events = getFilteredEvents();
  updateCount(events);

  if (currentView === 'list') {
    renderEvents(events);
  } else if (currentView === 'calendar') {
    renderCalendar(events);
  }
}

// ─── Event Count ─────────────────────────────────────────
function updateCount(events) {
  const existingCount = document.getElementById("event-count");
  if (existingCount) existingCount.remove();
  const countEl = document.createElement("p");
  countEl.id = "event-count";
  countEl.style.cssText = "text-align:center; color:#a89888; margin-bottom:1rem;";
  const label = showingPast ? 'past' : 'upcoming';
  countEl.textContent = `${events.length} ${label} event${events.length !== 1 ? 's' : ''}`;

  if (currentView === 'list') {
    eventList.before(countEl);
  } else if (currentView === 'calendar') {
    calendarContainer.before(countEl);
  }
}

// ─── View Switching ──────────────────────────────────────
function switchView(view) {
  currentView = view;

  [viewListBtn, viewCalendarBtn].forEach(btn => {
    btn.style.opacity = '0.5';
    btn.style.fontWeight = 'normal';
  });

  const activeBtn = view === 'list' ? viewListBtn : viewCalendarBtn;
  activeBtn.style.opacity = '1';
  activeBtn.style.fontWeight = '700';

  eventList.style.display = view === 'list' ? '' : 'none';
  calendarContainer.style.display = view === 'calendar' ? '' : 'none';

  const pagination = document.getElementById("pagination");
  if (pagination) pagination.style.display = view === 'list' ? '' : 'none';
  const printBtn = document.querySelector('.print-button');
  if (printBtn) printBtn.style.display = (view === 'list' && window.innerWidth >= 768) ? '' : 'none';

  refresh();
}

viewListBtn.addEventListener('click', () => switchView('list'));
viewCalendarBtn.addEventListener('click', () => switchView('calendar'));

viewListBtn.style.opacity = '1';
viewListBtn.style.fontWeight = '700';
viewCalendarBtn.style.opacity = '0.5';

// ─── Report Event (via RPC) ─────────────────────────────
async function reportEvent(eventId, btn) {
  if (hasReported(eventId)) {
    btn.textContent = 'Already reported';
    btn.disabled = true;
    return;
  }

  btn.textContent = 'Reporting…';
  btn.disabled = true;

  const { error } = await supabase.rpc('report_event', { event_id: eventId });

  if (error) {
    console.error('Report error:', error);
    btn.textContent = '🚩 Report';
    btn.disabled = false;
    return;
  }

  markReported(eventId);
  btn.textContent = '✓ Reported';

  // Reload to check if threshold reached
  setTimeout(() => loadEvents(), 1000);
}

// ─── List View ───────────────────────────────────────────
function renderEvents(events) {
  eventList.innerHTML = "";

  if (events.length === 0) {
    eventList.innerHTML = `<p style="text-align:center; color:#a89888;">${showingPast ? 'No past events found.' : 'No events match your search.'}</p>`;
    return;
  }

  const start = (currentPage - 1) * eventsPerPage;
  const end = start + eventsPerPage;
  const paginated = events.slice(start, end);

  paginated.forEach(event => {
    const div = document.createElement("div");
    div.className = "event";

    if (showingPast) {
      div.style.opacity = "0.6";
    }

    const dateStr = event.end_date && event.end_date !== event.start_date
      ? `${formatDate(event.start_date)} – ${formatDate(event.end_date)}`
      : formatDate(event.start_date);

    const alreadyReported = hasReported(event.id);

    div.innerHTML = `
      ${showingPast ? '<span style="background:#3d3028; color:#a89888; padding:2px 8px; border-radius:4px; font-size:0.75rem; float:right;">PAST</span>' : ''}
      <h3>${event.title}</h3>
      <p><strong>Date:</strong> ${dateStr}</p>
      <p><strong>Location:</strong>
        <a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(event.location)}" target="_blank" rel="noopener">
          ${event.location}
        </a>
      </p>
      ${event.tribe ? `<p><strong>Tribe / Group:</strong> ${event.tribe}</p>` : ''}
      ${event.details ? `<p><strong>Details:</strong> ${event.details}</p>` : ''}
      ${event.flyer_url ? `
        <a href="${event.flyer_url}" target="_blank" rel="noopener" style="display:block; text-align:center;">
          <img src="${event.flyer_url}" alt="Event flyer for ${event.title}" class="flyer-preview"
            style="max-width:250px; border-radius:8px; border:2px solid #3d3028; margin:10px auto; display:block;" />
        </a>
        <p style="font-size:0.8rem; color:#a89888;">Tap flyer to view full size</p>
      ` : '<p><em>No flyer available</em></p>'}
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0.5rem; flex-wrap:wrap; gap:0.5rem;">
        <button class="share-btn" data-title="${event.title}" data-id="${event.id}" style="background:none; border:1px solid #3d3028; color:#a89888; padding:4px 10px; border-radius:6px; cursor:pointer; font-size:0.8rem;">📤 Share</button>
        <button class="report-btn" data-id="${event.id}" style="background:none; border:1px solid #3d3028; color:#a89888; padding:4px 10px; border-radius:6px; cursor:pointer; font-size:0.8rem;" ${alreadyReported ? 'disabled' : ''}>${alreadyReported ? '✓ Reported' : '🚩 Report'}</button>
      </div>
    `;

    eventList.appendChild(div);

    div.querySelector('.share-btn').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const title = btn.dataset.title;
      const url = `${window.location.origin}${window.location.pathname}?event=${btn.dataset.id}`;

      if (navigator.share) {
        try {
          await navigator.share({ title: `Handgame: ${title}`, url });
        } catch (err) { /* user cancelled */ }
      } else {
        const ta = document.createElement('textarea');
        ta.value = url;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        btn.textContent = '✅ Copied!';
        setTimeout(() => { btn.textContent = '📤 Share'; }, 2000);
      }
    });

    div.querySelector('.report-btn').addEventListener('click', (e) => {
      const btn = e.currentTarget;
      reportEvent(btn.dataset.id, btn);
    });
  });

  renderPagination(events);
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const [year, month, day] = dateStr.split('-');
  const d = new Date(Number(year), Number(month) - 1, Number(day));
  return d.toLocaleDateString('en-US', { weekday: 'short', year: 'numeric', month: 'long', day: 'numeric' });
}

function renderPagination(events) {
  let paginationDiv = document.getElementById("pagination");
  if (!paginationDiv) {
    paginationDiv = document.createElement("div");
    paginationDiv.id = "pagination";
    paginationDiv.style.cssText = "text-align:center; margin-top:1rem;";
    document.querySelector("main").appendChild(paginationDiv);
  }
  paginationDiv.innerHTML = "";

  const totalPages = Math.ceil(events.length / eventsPerPage);
  if (totalPages <= 1) return;

  for (let i = 1; i <= totalPages; i++) {
    const btn = document.createElement("button");
    btn.textContent = i;
    btn.className = i === currentPage ? "active-page" : "";
    btn.onclick = () => {
      currentPage = i;
      renderEvents(getFilteredEvents());
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
    paginationDiv.appendChild(btn);
  }
}

// ─── Calendar View (earth tones) ─────────────────────────
function renderCalendar(events) {
  const year = calendarDate.getFullYear();
  const month = calendarDate.getMonth();
  const monthName = calendarDate.toLocaleString('en-US', { month: 'long', year: 'numeric' });

  const eventDates = {};
  events.forEach(event => {
    const start = new Date(event.start_date + 'T00:00:00');
    const end = event.end_date ? new Date(event.end_date + 'T00:00:00') : start;
    const d = new Date(start);
    while (d <= end) {
      if (d.getMonth() === month && d.getFullYear() === year) {
        const key = d.getDate();
        if (!eventDates[key]) eventDates[key] = [];
        eventDates[key].push(event);
      }
      d.setDate(d.getDate() + 1);
    }
  });

  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();

  let html = `
    <div style="max-width:400px; margin:0 auto; font-family:'JetBrains Mono', monospace;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
        <button id="cal-prev" style="background:none; border:1px solid #4a3c30; color:#e8ddd0; padding:4px 12px; border-radius:6px; cursor:pointer; font-size:1.2rem;">◀</button>
        <strong style="font-size:1.1rem; color:#e6a530;">${monthName}</strong>
        <button id="cal-next" style="background:none; border:1px solid #4a3c30; color:#e8ddd0; padding:4px 12px; border-radius:6px; cursor:pointer; font-size:1.2rem;">▶</button>
      </div>
      <div style="display:grid; grid-template-columns:repeat(7, 1fr); text-align:center; gap:2px;">
        <div style="color:#a89888; font-size:0.8rem; padding:4px;">Su</div>
        <div style="color:#a89888; font-size:0.8rem; padding:4px;">Mo</div>
        <div style="color:#a89888; font-size:0.8rem; padding:4px;">Tu</div>
        <div style="color:#a89888; font-size:0.8rem; padding:4px;">We</div>
        <div style="color:#a89888; font-size:0.8rem; padding:4px;">Th</div>
        <div style="color:#a89888; font-size:0.8rem; padding:4px;">Fr</div>
        <div style="color:#a89888; font-size:0.8rem; padding:4px;">Sa</div>
  `;

  for (let i = 0; i < firstDay; i++) {
    html += `<div style="padding:8px;"></div>`;
  }

  for (let day = 1; day <= daysInMonth; day++) {
    const hasEvent = eventDates[day];
    const isToday = today.getDate() === day && today.getMonth() === month && today.getFullYear() === year;

    let style = 'padding:6px; border-radius:6px; font-size:0.9rem; position:relative; ';
    if (isToday) style += 'border:1px solid #3dbead; ';
    if (hasEvent) style += 'cursor:pointer; background:#2a2018; font-weight:700; color:#d4723c; ';
    else style += 'color:#a89888; ';

    const dot = hasEvent ? `<span style="display:block; width:5px; height:5px; background:#d4723c; border-radius:50%; margin:2px auto 0;"></span>` : '';
    const count = hasEvent && hasEvent.length > 1 ? `<span style="font-size:0.6rem; position:absolute; top:2px; right:4px; color:#a89888;">${hasEvent.length}</span>` : '';

    html += `<div class="cal-day" data-day="${day}" style="${style}">${count}${day}${dot}</div>`;
  }

  html += `</div></div>`;
  html += `<div id="cal-day-events" style="margin-top:1rem;"></div>`;

  calendarContainer.innerHTML = html;

  document.getElementById('cal-prev').addEventListener('click', () => {
    calendarDate.setMonth(calendarDate.getMonth() - 1);
    refresh();
  });
  document.getElementById('cal-next').addEventListener('click', () => {
    calendarDate.setMonth(calendarDate.getMonth() + 1);
    refresh();
  });

  calendarContainer.querySelectorAll('.cal-day[data-day]').forEach(cell => {
    cell.addEventListener('click', () => {
      const day = parseInt(cell.dataset.day);
      const dayEvents = eventDates[day];
      const dayEventsDiv = document.getElementById('cal-day-events');

      if (!dayEvents || dayEvents.length === 0) {
        dayEventsDiv.innerHTML = `<p style="text-align:center; color:#a89888;">No events on ${monthName.split(' ')[0]} ${day}.</p>`;
        return;
      }

      let evHtml = `<h3 style="text-align:center; margin-bottom:0.5rem; color:#e6a530;">Events on ${monthName.split(' ')[0]} ${day}</h3>`;
      dayEvents.forEach(event => {
        const dateStr = event.end_date && event.end_date !== event.start_date
          ? `${formatDate(event.start_date)} – ${formatDate(event.end_date)}`
          : formatDate(event.start_date);

        evHtml += `
          <div style="border:1px solid #3d3028; border-left:4px solid #d4723c; border-radius:8px; padding:1rem; margin-bottom:0.75rem; background:#1c1612;">
            <h4 style="color:#e6a530;">${event.title}</h4>
            <p><strong>Date:</strong> ${dateStr}</p>
            <p><strong>Location:</strong>
              <a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(event.location)}" target="_blank" rel="noopener" style="color:#3dbead;">${event.location}</a>
            </p>
            ${event.tribe ? `<p><strong>Tribe / Group:</strong> ${event.tribe}</p>` : ''}
            ${event.details ? `<p><strong>Details:</strong> ${event.details}</p>` : ''}
            ${event.flyer_url ? `
              <a href="${event.flyer_url}" target="_blank" rel="noopener" style="display:block; text-align:center;">
                <img src="${event.flyer_url}" alt="Event flyer for ${event.title}"
                  style="max-width:250px; border-radius:8px; border:2px solid #3d3028; margin:10px auto; display:block;" />
              </a>
              <p style="font-size:0.8rem; color:#a89888; text-align:center;">Tap flyer to view full size</p>
            ` : ''}
          </div>
        `;
      });

      dayEventsDiv.innerHTML = evHtml;
    });
  });
}

// ─── Toggle Past Events ─────────────────────────────────
togglePastBtn.addEventListener("click", () => {
  showingPast = !showingPast;
  currentPage = 1;
  togglePastBtn.textContent = showingPast ? "Show Upcoming Events" : "Show Past Events";
  refresh();
});

// ─── Search ──────────────────────────────────────────────
searchInput.addEventListener("input", () => {
  currentPage = 1;
  refresh();
});

// ─── Init ────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", loadEvents);