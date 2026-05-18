import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';

const supabaseUrl = 'https://atorftwulkabkmhaeeir.supabase.co';
const supabaseKey = 'sb_publishable_0CKKNOHPd3Yd6bDfkEuHlA_YgS9bJvF';
const supabase = createClient(supabaseUrl, supabaseKey);

let currentPage = 1;
const eventsPerPage = 3;

const eventList = document.getElementById("event-list");
const searchInput = document.getElementById("search");
let allEvents = [];

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

  allEvents = data.filter(event => {
    const eventDate = new Date(event.start_date);
    return eventDate >= today;
  });

  if (allEvents.length === 0) {
    eventList.innerHTML = '<p style="text-align:center; color:#aaa;">No upcoming events right now. Check back soon or <a href="submission.html">submit one</a>!</p>';
    return;
  }

  renderEvents(allEvents);
}

function renderEvents(events) {
  eventList.innerHTML = "";

  if (events.length === 0) {
    eventList.innerHTML = '<p style="text-align:center; color:#aaa;">No events match your search.</p>';
    return;
  }

  const start = (currentPage - 1) * eventsPerPage;
  const end = start + eventsPerPage;
  const paginated = events.slice(start, end);

  paginated.forEach(event => {
    const div = document.createElement("div");
    div.className = "event";

    const dateStr = event.end_date && event.end_date !== event.start_date
      ? `${formatDate(event.start_date)} – ${formatDate(event.end_date)}`
      : formatDate(event.start_date);

    div.innerHTML = `
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
    `;

    eventList.appendChild(div);
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
      renderEvents(events);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
    paginationDiv.appendChild(btn);
  }
}

// Live search
searchInput.addEventListener("input", e => {
  const query = e.target.value.toLowerCase();
  currentPage = 1;
  const filtered = allEvents.filter(event =>
    (event.title    || "").toLowerCase().includes(query) ||
    (event.location || "").toLowerCase().includes(query) ||
    (event.tribe    || "").toLowerCase().includes(query) ||
    (event.details  || "").toLowerCase().includes(query)
  );
  renderEvents(filtered);
});

window.addEventListener("DOMContentLoaded", loadEvents);
