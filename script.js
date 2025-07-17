import { supabase } from './supabaseClient.js';

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
  const { title, start_date, end_date, location = 'Not Available', tribe = 'Not Available', details, flyer_url } = event;

  const formattedDetails = details ? highlightMatch(details.replace(/\n/g, '<br>'), searchTerm) : '';

  const isImage = /\.(jpg|jpeg|png|gif|webp|bmp|tiff|svg)$/i.test(flyer_url || '');
  let flyerHTML = '';

  if (flyer_url?.trim()) {
    flyerHTML = isImage
      ? `<a href="${flyer_url}" target="_blank">
           <img src="${flyer_url}" alt="Flyer" class="flyer-img"
                onerror="this.style.display='none'; this.nextElementSibling?.classList.add('show-error');">
         </a>
         <p class="flyer-error" style="display:none; color:red; font-size: 0.9rem;">⚠️ Flyer failed to load.</p>
         <p><a href="${flyer_url}" target="_blank" class="flyer-link">📄 View Flyer</a></p>`
      : `<p><a href="${flyer_url}" target="_blank" class="flyer-link">📎 View Flyer Link</a></p>`;
  }

  return `
    <div class="event">
      <h2>${highlightMatch(title, searchTerm)}</h2>
      <p><strong>Dates:</strong> ${formatDate(start_date)}${end_date ? ' – ' + formatDate(end_date) : ''}</p>
      <p><strong>Location:</strong> ${highlightMatch(location.trim(), searchTerm)}<br>
        <a href="https://www.google.com/maps/search/${encodeURIComponent(location)}" target="_blank">📍 View on Map</a>
      </p>
      <p><strong>Tribe/Group:</strong> ${highlightMatch(tribe.trim(), searchTerm)}</p>
      ${flyerHTML}
      ${formattedDetails ? `
        <button class="toggle-details-button">Show Details</button>
        <div class="event-details" style="display: none;">
          <p><strong>Details:</strong><br>${formattedDetails}</p>
        </div>` : ''}
      <p class="mobile-details-msg">Full details available on desktop view.</p>
      <p class="countdown">⏳ ${renderCountdown(end_date || start_date)}</p>
    </div>
  `;
}

function render(events, searchTerm = '') {
  const container = document.getElementById('event-list');
  container.innerHTML = '';

  const upcoming = events
    .filter(e => isUpcoming(e.start_date))
    .sort((a, b) => new Date(a.start_date) - new Date(b.start_date));

  const showLimit = 5;

  upcoming.forEach((event, index) => {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = createEventHTML(event, searchTerm);
    if (index >= showLimit) {
      wrapper.style.display = 'none';
      wrapper.classList.add('extra-upcoming');
    }
    container.appendChild(wrapper);
  });

  if (upcoming.length > showLimit) {
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
      const details = this.nextElementSibling;
      const visible = details.style.display === 'block';
      details.style.display = visible ? 'none' : 'block';
      this.textContent = visible ? 'Show Details' : 'Hide Details';
    });
  });

  // Filter shortcuts
  document.querySelectorAll('.filter-button').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = document.getElementById('search');
      input.value = btn.dataset.filter;
      input.dispatchEvent(new Event('input'));
    });
  });

  const clearBtn = document.getElementById('clear-search');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      const input = document.getElementById('search');
      input.value = '';
      input.dispatchEvent(new Event('input'));
    });
  }
}

function fuzzyMatch(term, str) {
  return str?.toLowerCase().includes(term?.toLowerCase());
}

async function loadEvents() {
  try {
    const { data: events, error } = await supabase
      .from('events')
      .select('*')
      .order('start_date', { ascending: true });

    if (error) throw error;

    render(events);

    const searchInput = document.getElementById('search');
    searchInput.addEventListener('input', function () {
      const term = this.value.toLowerCase();
      if (!term) return render(events);

      const filtered = events.filter(e =>
        fuzzyMatch(term, e.title) ||
        fuzzyMatch(term, e.location) ||
        fuzzyMatch(term, e.tribe) ||
        fuzzyMatch(term, e.details) ||
        fuzzyMatch(term, e.start_date) ||
        fuzzyMatch(term, e.end_date)
      );

      render(filtered, term);
    });

    // Optional: auto-refresh countdowns every minute
    setInterval(() => render(events), 60000);
  } catch (error) {
    console.error('Failed to load events:', error);
    const container = document.getElementById('event-list');
    container.innerHTML = `<p style="color:red;text-align:center;">Could not load event data. Please try again later.</p>`;
  }
}

// Startup
window.addEventListener('DOMContentLoaded', () => {
  const storedTheme = localStorage.getItem('theme');
  if (storedTheme === 'light') {
    document.body.classList.add('light-mode');
  } else {
    localStorage.setItem('theme', 'dark');
  }

  loadEvents();
});
