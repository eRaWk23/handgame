const SHEET_URL = 'https://opensheet.elk.sh/1ZIux92KejqcpA1RFilkWrd2k37AkewHOLP-bzyVWGHo/Form%20Responses%201';

function isUpcoming(dateStr) {
  const now = new Date();
  const eventDate = new Date(dateStr);
  return eventDate > now;
}

function renderCountdown(dateStr) {
  const now = new Date();
  const eventDate = new Date(dateStr);
  const diff = eventDate - now;

  if (diff <= 0) return 'Happened already';

  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  const hours = Math.floor((diff / (1000 * 60 * 60)) % 24);
  const minutes = Math.floor((diff / (1000 * 60)) % 60);

  return `${days}d ${hours}h ${minutes}m till event`;
}

function formatDate(dateStr) {
  const date = new Date(dateStr);
  if (isNaN(date)) return dateStr;
  return date.toLocaleDateString(undefined, {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
}

function highlightMatch(text, term) {
  if (!text || !term) return text;
  const regex = new RegExp(`(${term})`, 'gi');
  return text.replace(regex, '<mark>$1</mark>');
}

function render(events, searchTerm = '') {
  const container = document.getElementById('event-list');
  container.innerHTML = '';

  if (events.length === 0) {
    container.innerHTML = '<p style="text-align: center; font-size: 1.25rem;">No events found.</p>';
    return;
  }

  const upcomingEvents = events.filter(event => isUpcoming(event["Start Date"]));
  const pastEvents = events.filter(event => !isUpcoming(event["End Date"]));

  upcomingEvents.forEach(event => {
    const title = event["Event Title"];
    const startDate = event["Start Date"];
    const endDate = event["End Date"];
    const location = event["Location"];
    const tribe = event["Tribe (optional)"];
    const flyer = event["Flyer Link (optional)"];
    const rawDetails = event["Details (optional)"];
    const formattedDetails = rawDetails ? highlightMatch(rawDetails.replace(/\n/g, '<br>'), searchTerm) : '';

    let flyerHTML = '';
    const allImageExtensions = /\.(jpg|jpeg|png|gif|webp|bmp|tiff|svg)$/i;
    const driveLink = event["Upload Flyer (optional)"];
    let previewLink = '';
    let viewerLink = '';

    if (driveLink && driveLink.includes('drive.google.com')) {
      const idMatch = driveLink.match(/[-\w]{25,}/);
      if (idMatch) {
        const fileId = idMatch[0];
        previewLink = `https://drive.google.com/uc?export=view&id=${fileId}`;
        viewerLink = `https://drive.google.com/file/d/${fileId}/view`;

        flyerHTML = `
          <a href="${viewerLink}" target="_blank">
            <img src="${previewLink}" alt="Flyer for Event" class="flyer-img" onerror="this.style.display='none'">
          </a>
          <p><a href="${viewerLink}" target="_blank" class="flyer-link">📄 View Flyer</a></p>`;
      }
    } else if (flyer) {
      previewLink = flyer;
      viewerLink = flyer;

      if (allImageExtensions.test(previewLink)) {
        flyerHTML = `
          <a href="${viewerLink}" target="_blank">
            <img src="${previewLink}" alt="Flyer for Event" class="flyer-img" onerror="this.style.display='none'">
          </a>
          <p><a href="${viewerLink}" target="_blank" class="flyer-link">📄 View Flyer</a></p>`;
      } else {
        flyerHTML = `<p><a href="${viewerLink}" target="_blank" class="flyer-link">📎 View Flyer Link</a></p>`;
      }
    }

    const eventHTML = `
      <div class="event">
        <h2>${highlightMatch(title, searchTerm)}</h2>
        <p><strong>Dates:</strong> ${formatDate(startDate)} ${endDate ? '– ' + formatDate(endDate) : ''}</p>
        <p><strong>Location:</strong> 
         <button class="filter-button" data-filter="${location}">${highlightMatch(location, searchTerm)}</button>
         <br>
         <a href="https://www.google.com/maps/search/${encodeURIComponent(location)}" target="_blank" style="font-size: 0.95rem;">📍 View on Map</a>
        </p>

        <p><strong>Tribe/Group:</strong> <button class="filter-button" data-filter="${tribe}">${highlightMatch(tribe, searchTerm)}</button></p>
        ${flyerHTML}
        <br>
        ${formattedDetails ? `
        <button class="toggle-details-button">Show Details</button>
        <div class="event-details" style="display: none;">
            <p><strong>Details:</strong><br>${formattedDetails}</p>
        </div>
        ` : ''}
        <p class="countdown">⏳ ${renderCountdown(endDate || startDate)}</p>
      </div>
    `;

    container.insertAdjacentHTML('beforeend', eventHTML);
  });

  document.querySelectorAll('.toggle-details-button').forEach(button => {
    button.addEventListener('click', () => {
      const detailsDiv = button.nextElementSibling;
      const isVisible = detailsDiv.style.display === 'block';
      detailsDiv.style.display = isVisible ? 'none' : 'block';
      button.textContent = isVisible ? 'Show Details' : 'Hide Details';
    });
  });

  document.querySelectorAll('.filter-button').forEach(btn => {
    btn.addEventListener('click', () => {
      const search = document.getElementById('search');
      search.value = btn.dataset.filter;
      search.dispatchEvent(new Event('input'));
    });
  });

  const clearBtn = document.getElementById('clear-search');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      const searchInput = document.getElementById('search');
      searchInput.value = '';
      searchInput.dispatchEvent(new Event('input'));
    });
  }

  window.pastEventsArchive = pastEvents;
}

function fuzzyMatch(term, str) {
  if (!term || !str) return false;
  return str.toLowerCase().includes(term);
}

async function loadEvents() {
  try {
    const response = await fetch(SHEET_URL);
    if (!response.ok) throw new Error('Failed to fetch event data.');
    const events = await response.json();

    render(events);

    const searchInput = document.getElementById('search');
    searchInput.addEventListener('input', function () {
      const term = this.value.toLowerCase();
      if (term === '') {
        render(events); 
        return;
      }
      const filtered = events.filter(e =>
        fuzzyMatch(term, e["Event Title"]?.toLowerCase()) ||
        fuzzyMatch(term, e["Location"]?.toLowerCase()) ||
        fuzzyMatch(term, e["Tribe (optional)"]?.toLowerCase()) ||
        fuzzyMatch(term, e["Start Date"]?.toLowerCase()) ||
        fuzzyMatch(term, e["End Date"]?.toLowerCase()) ||
        fuzzyMatch(term, e["Details (optional)"]?.toLowerCase())
      );
      render(filtered, term);
    });

    setInterval(() => render(events), 60000);

  } catch (error) {
    console.error('Error loading events:', error);
    const container = document.getElementById('event-list');
    container.innerHTML = '<p style="color: red; text-align: center;">Could not load event data. Please try again later.</p>';
  }
}

window.addEventListener('DOMContentLoaded', loadEvents);
