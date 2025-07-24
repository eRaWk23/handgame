import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';

// 🔐 Replace this with your actual anon key
const supabaseUrl = 'https://ulnoqchwdlcaneifogdz.supabase.co';
const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVsbm9xY2h3ZGxjYW5laWZvZ2R6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTI3ODkzODAsImV4cCI6MjA2ODM2NTM4MH0.cuBr-_Fe4lmHdu85hSF39Z60vb8Ogfue57TeJmPKPVQ';
const supabase = createClient(supabaseUrl, supabaseKey);

const eventList = document.getElementById("event-list");
const searchInput = document.getElementById("search");
const modal = document.getElementById("event-modal");
const modalTitle = document.getElementById("modal-title");
const modalDate = document.getElementById("modal-date");
const modalLocation = document.getElementById("modal-location");
const modalTribe = document.getElementById("modal-tribe");
const modalFlyer = document.getElementById("modal-flyer");
const modalDetails = document.getElementById("modal-details");

let allEvents = [];

async function loadEvents() {
  try {
    const { data, error } = await supabase
      .from("events")
      .select("*")
      .order("start_date", { ascending: true });

    if (error) throw error;

    allEvents = data;
    renderEvents(data);
  } catch (err) {
    console.error("Failed to load events:", err);
    eventList.innerHTML = `<p style="text-align:center;">Could not load event data. Please try again later.</p>`;
  }
}

function renderEvents(events) {
  if (!events || events.length === 0) {
    eventList.innerHTML = `<p style="text-align:center;">No events found.</p>`;
    return;
  }

  eventList.innerHTML = "";
  events.forEach(event => {
    const div = document.createElement("div");
    div.className = "event-card";
    div.innerHTML = `
      <h3>${event.title}</h3>
      <p><strong>Date:</strong> ${event.start_date || "N/A"}</p>
      <p><strong>Location:</strong> ${event.location || "N/A"}</p>
      <p><strong>Tribe:</strong> ${event.tribe || "N/A"}</p>
      <p><strong>Details:</strong> ${event.details || "N/A"}</p>
    `;

    div.addEventListener("click", () => openModal(event));
    eventList.appendChild(div);
  });
}

function openModal(event) {
  modalTitle.textContent = event.title || "No Title";
  modalDate.textContent = event.start_date || "N/A";
  modalLocation.textContent = event.location || "N/A";
  modalTribe.textContent = event.tribe || "N/A";
  modalDetails.textContent = event.details || "N/A";

  if (event.flyer_url) {
    modalFlyer.innerHTML = `<img src="${event.flyer_url}" alt="Flyer" style="max-width:100%;">`;
  } else {
    modalFlyer.innerHTML = `<p><em>No flyer available</em></p>`;
  }

  modal.style.display = "block";
}

document.querySelector(".close-button").onclick = () => {
  modal.style.display = "none";
};

window.onclick = e => {
  if (e.target == modal) modal.style.display = "none";
};

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

window.addEventListener("DOMContentLoaded", loadEvents);
