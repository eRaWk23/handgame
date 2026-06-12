import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';

const supabaseUrl = 'https://atorftwulkabkmhaeeir.supabase.co';
const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF0b3JmdHd1bGthYmttaGFlZWlyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzkwNDk5MTQsImV4cCI6MjA5NDYyNTkxNH0.SW0OdvAZvAh81PqpLkez1MO8WnMruQxMoCitpcd-PMs';
const supabase = createClient(supabaseUrl, supabaseKey);

let currentPage = 1;
const eventsPerPage = 3;

const eventList = document.getElementById("event-list");
const searchInput = document.getElementById("search");
const togglePastBtn = document.getElementById("toggle-past");

let allEvents = [];
let pastEvents = [];
let showingPast = false;

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

  allEvents = data.filter(event => new Date(event.start_date) >= today);
  pastEvents = data.filter(event => new Date(event.start_date) < today).reverse();

  if (allEvents.length === 0 && !showingPast) {
    eventList.innerHTML = '<p style="text-align:center; color:#aaa;">No upcoming events right now. Check back soon or <a href="submission.html">submit one</a>!</p>';
  }

  updateCount();
  renderEvents(getActiveEvents());
}

function getActiveEvents() {
  return showingPast ? pastEvents : allEvents;
}

function updateCount() {
  const existingCount = document.getElementById("event-count");
  if (existingCount) existingCount.remove();
  const events = getActiveEvents();
  const countEl = document.createElement("p");
  countEl.id = "event-count";
  countEl.style.cssText = "text-align:center; color:#aaa; margin-bottom:1rem;";
  if (showingPast) {
    countEl.textContent = `${events.length} past event${events.length !== 1 ? 's' : ''}`;
  } else {
    countEl.textContent = `${events.length} upcoming event${events.length !== 1 ? 's' : ''}`;
  }
  eventList.before(countEl);
}

function renderEvents(events) {
  eventList.innerHTML = "";

  if (events.length === 0) {
    eventList.innerHTML = `<p style="text-align:center; color:#aaa;">${showingPast ? 'No past events found.' : 'No events match your search.'}</p>`;
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

    div.innerHTML = `
      ${showingPast ? '<span style="background:#555; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.75rem; float:right;">PAST</span>' : ''}
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
            style="max-width:250px; border-radius:8px; border:2px solid #999; margin:10px auto; display:block;" />
        </a>
        <p style="font-size:0.8rem; color:#aaa;">Tap flyer to view full size</p>
      ` : '<p><em>No flyer available</em></p>'}
      <div style="text-align:right; margin-top:0.5rem;">
        <button class="share-btn" data-title="${event.title}" data-id="${event.id}" style="background:none; border:1px solid #666; color:#aaa; padding:4px 10px; border-radius:6px; cursor:pointer; font-size:0.8rem;">📤 Share</button>
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
        await navigator.clipboard.writeText(url);
        btn.textContent = '✅ Link copied!';
        setTimeout(() => { btn.textContent = '📤 Share'; }, 2000);
      }
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
      renderEvents(getActiveEvents());
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
    paginationDiv.appendChild(btn);
  }
}

// Toggle past events
togglePastBtn.addEventListener("click", () => {
  showingPast = !showingPast;
  currentPage = 1;
  togglePastBtn.textContent = showingPast ? "Show Upcoming Events" : "Show Past Events";
  updateCount();
  renderEvents(getActiveEvents());
});

// Live search
searchInput.addEventListener("input", e => {
  const query = e.target.value.toLowerCase();
  currentPage = 1;
  const events = getActiveEvents();
  const filtered = events.filter(event =>
    (event.title    || "").toLowerCase().includes(query) ||
    (event.location || "").toLowerCase().includes(query) ||
    (event.tribe    || "").toLowerCase().includes(query) ||
    (event.details  || "").toLowerCase().includes(query)
  );
  renderEvents(filtered);
});

window.addEventListener("DOMContentLoaded", loadEvents);