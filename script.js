import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';

// 🔐 Supabase settings
const supabaseUrl = 'https://ulnoqchwdlcaneifogdz.supabase.co';
const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVsbm9xY2h3ZGxjYW5laWZvZ2R6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTI3ODkzODAsImV4cCI6MjA2ODM2NTM4MH0.cuBr-_Fe4lmHdu85hSF39Z60vb8Ogfue57TeJmPKPVQ';
const supabase = createClient(supabaseUrl, supabaseKey);

let currentPage = 1;
const eventsPerPage = 3;

// DOM elements
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
    return;
  }

  const today = new Date();

  // Filter to only show upcoming or recent events (today or future)
  const upcomingEvents = data.filter(event => {
    const eventDate = new Date(event.start_date);
    return eventDate >= today;
  });

  renderEvents(upcomingEvents);
}

function renderEvents(events) {
  eventList.innerHTML = "";

  const start = (currentPage - 1) * eventsPerPage;
  const end = start + eventsPerPage;
  const paginatedEvents = events.slice(start, end);

  paginatedEvents.forEach(event => {
    const eventDiv = document.createElement("div");
    eventDiv.className = "event";

    eventDiv.innerHTML = `
      <h3>${event.title}</h3>
      <p><strong>Date:</strong> ${event.start_date}</p>
      <p><strong>Location:</strong> 
        <a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(event.location)}" target="_blank">
          ${event.location}
        </a>
      </p>
      <p><strong>Tribe/Group:</strong> ${event.tribe || "Not provided"}</p>
      ${event.flyer_url ? `
        <a href="${event.flyer_url}" target="_blank">
          <img src="${event.flyer_url}" alt="Flyer preview" class="flyer-preview" style="max-width: 250px; border-radius: 8px; border: 2px solid #999; margin: 10px 0;" />
        </a>
        <p style="font-size: 0.8rem;">Click flyer to view full size</p>
      ` : `<p><em>No flyer available</em></p>`}
      <p><strong>Details:</strong> ${event.details || "None provided"}</p>
    `;

    eventList.appendChild(eventDiv);
  });

  renderPagination(events);
}

function renderPagination(events) {
  let paginationDiv = document.getElementById("pagination");

  if (!paginationDiv) {
    paginationDiv = document.createElement("div");
    paginationDiv.id = "pagination";
    paginationDiv.style.textAlign = "center";
    paginationDiv.style.marginTop = "1rem";
    document.querySelector("main").appendChild(paginationDiv);
  }

  paginationDiv.innerHTML = "";

  const totalPages = Math.ceil(events.length / eventsPerPage);

  for (let i = 1; i <= totalPages; i++) {
    const btn = document.createElement("button");
    btn.textContent = i;
    btn.className = i === currentPage ? "active-page" : "";
    btn.onclick = () => {
      currentPage = i;
      renderEvents(events);
    };
    paginationDiv.appendChild(btn);
  }
}

// 🔍 Live search
searchInput.addEventListener("input", e => {
  const query = e.target.value.toLowerCase();
  const filtered = allEvents.filter(event =>
    (event.title || "").toLowerCase().includes(query) ||
    (event.location || "").toLowerCase().includes(query) ||
    (event.tribe || "").toLowerCase().includes(query) ||
    (event.details || "").toLowerCase().includes(query)
  );
  renderEvents(filtered);
});

// 🚀 Load events on page load
window.addEventListener("DOMContentLoaded", loadEvents);
