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

function createEventHTML(event, searchTerm = '') {
  const title = event["Event Title"];
  const startDate = event["Start Date"];
  const endDate = event["End Date"];
  const location = event["Location"]?.trim() || "Not Available";
  const tribe = event["Tribe (optional)"]?.trim() || "Not Available";
  const rawDetails = event["Details (optional)"];
  const formattedDetails = rawDetails ? highlightMatch(rawDetails.replace(/\n/g, '<br>'), searchTerm) : '';

  const driveLink = event["Upload Flyer (optional)"]?.trim();
  const flyerLink = event["Flyer Link (optional)"]?.trim();
  const allImageExtensions = /\.(jpg|jpeg|png|gif|webp|bmp|tiff|svg)$/i;

  let finalLink = '';
  let previewSrc = '';
  let isImage = false;

  if (driveLink && driveLink.includes('drive.google.com')) {
    const idMatch = driveLink.match(/[-\w]{25,}/);
    if (idMatch) {
      const fileId = idMatch[0];
      finalLink = `https://drive.google.com/file/d/${fileId}/view`;
      previewSrc = `https://drive.google.com/uc?export=view&id=${fileId}`;
      isImage = true;
    }
  }

  if (!finalLink && flyerLink) {
    finalLink = flyerLink;
    previewSrc = flyerLink;
    isImage = allImageExtensions.test(flyerLink);
  }

  let flyerHTML = '';
  if (finalLink) {
    flyerHTML = isImage
      ? `<a href="${finalLink}" target="_blank"><img src="${previewSrc}" alt="Flyer" class="flyer-img" onerror="this.style.display='none'; this.nextElementSibling?.classList.add('show-error');"></a>
         <p class="flyer-error" style="display:none; color:red; font-size: 0.9rem;">⚠️ Flyer failed to load.</p>
         <p><a href="${finalLink}" target="_blank" class="flyer-link">📄 View Flyer</a></p>`
      : `<p><a href="${finalLink}" target="_blank" class="flyer-link">📎 View Flyer Link</a></p>`;
  }

  return `
    <div class="event">
      <h2>${highlightMatch(title, searchTerm)}</h2>
      <p><strong>Dates:</strong> ${formatDate(startDate)}${endDate ? ' – ' + formatDate(endDate) : ''}</p>
      <p><strong>Location:</strong> ${highlightMatch(location, searchTerm)}<br>
      <a href="https://www.google.com/maps/search/${encodeURIComponent(location)}" target="_blank">📍 View on Map</a></p>
      <p><strong>Tribe/Group:</strong> ${highlightMatch(tribe, searchTerm)}</p>
      ${flyerHTML}
      ${formattedDetails ? `
        <button class="toggle-details-button">Show Details</button>
        <div class="event-details" style="display: none;">
          <p><strong>Details:</strong><br>${formattedDetails}</p>
        </div>
        <p class="mobile-details-msg">Full details available on desktop view.</p>
      ` : ''}
      <p class="countdown">⏳ ${renderCountdown(endDate || startDate)}</p>
    </div>
  `;
}

function render(events, searchTerm = '') {
  const container = document.getElementById('event-list');
  container.innerHTML = '';

  const upcomingEvents = events
    .filter(e => isUpcoming(e["Start Date"]))
    .sort((a, b) => new Date(a["Start Date"]) - new Date(b["Start Date"]));

  const showLimit = 5;

  upcomingEvents.forEach((event, index) => {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = createEventHTML(event, searchTerm);
    if (index >= showLimit) {
      wrapper.style.display = 'none';
      wrapper.classList.add('extra-upcoming');
    }
    container.appendChild(wrapper);
  });

  if (upcomingEvents.length > showLimit) {
    const btn = document.createElement('button');
    btn.textContent = 'Show More Events';
    btn.className = 'toggle-button';
    btn.onclick = () => {
      const extras = document.querySelectorAll('.extra-upcoming');
      const hidden = extras[0].style.display === 'none';
      extras.forEach(e => e.style.display = hidden ? 'block' : 'none');
      btn.textContent = hidden ? 'Show Fewer Events' : 'Show More Events';
    };
    container.appendChild(btn);
  }

  container.querySelectorAll('.toggle-details-button').forEach(btn => {
    btn.addEventListener('click', function () {
      const detailsDiv = this.nextElementSibling;
      if (!detailsDiv || !detailsDiv.classList.contains('event-details')) return;

      const isVisible = detailsDiv.style.display === 'block';
      detailsDiv.style.display = isVisible ? 'none' : 'block';
      this.textContent = isVisible ? 'Show Details' : 'Hide Details';
    });
  });

  // Filter buttons
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
