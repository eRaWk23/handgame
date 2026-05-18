# 🤲 Handgame Events

**[handgame.info](https://www.handgame.info)** — A community-powered site for sharing and discovering Native American Handgame events.

Find upcoming events, browse flyers, and submit your own — all in one place, on any device.

---

## What Is Handgame?

Handgame (also called the stick game or bone game) is a traditional Native American guessing game played across many Nations and tribes. It's a game of music, rhythm, intuition, and team spirit — often played at powwows, gatherings, and tribal celebrations. Different regions have their own songs, rules, and styles. If you grew up around it, you know. If you're new, come find out.

This site exists because event info was scattered across Facebook groups, text threads, and word of mouth. Now there's one place to check.

---

## What the Site Does

- 📅 Lists **upcoming Handgame events** — expired events hide automatically
- 🔎 **Search** by location, tribe, or keyword
- 🖼️ **Flyer previews** with download/view links
- ⚠️ Flags flyers older than 30 days so stale info is visible
- 📄 **Printable view** for posting at the hall or sharing at events
- 🌞🌙 Light/Dark mode — respects your system preference
- 📱 Fully mobile-friendly
- 🐢 Lightweight — works on slow connections

---

## How to Submit an Event

1. Go to **[handgame.info/submission.html](https://www.handgame.info/submission.html)**
2. Fill in the event title, date, and location
3. Upload a flyer or paste a link to one
4. Hit Submit — that's it

Submissions go into the database and appear on the main page once reviewed.

> **Have a flyer saved to your phone?** Just tap *Upload Flyer*, pick the image from your camera roll, and submit. No account needed.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Frontend | HTML + CSS + Vanilla JS |
| Database | [Supabase](https://supabase.com) (PostgreSQL) |
| Flyer storage | Supabase Storage |
| Hosting | GitHub Pages |
| Domain | `handgame.info` via CNAME |

No frameworks, no build step. Open the HTML in a browser and it works.

---

## Contributing

This project is open to pull requests. All help is welcome — code, design, bug reports, content.

### Getting Started (no install needed)

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/YOUR-USERNAME/handgame.git
cd handgame

# 2. Open in your browser — no server needed
open index.html
# or just drag index.html into a browser window
```

The site talks to the live Supabase backend, so you'll see real events right away.

### File Overview

```
handgame/
├── index.html        ← Main events listing page
├── about.html        ← About the site and the game
├── submission.html   ← Public event submission form
├── submission.css    ← Styles specific to the submission page
├── style.css         ← Global styles (dark/light mode, layout)
├── script.js         ← Fetches events from Supabase, renders cards
├── supabaseClient.js ← Supabase client setup
├── resources.html    ← Coming soon (currently disabled)
├── CNAME             ← Custom domain config for GitHub Pages
└── handgame.jpeg / handgameCA.jpg / handgameSticks.jpg
```

### Good First Issues

- Fix a typo or improve wording anywhere on the site
- Improve mobile layout or button sizing
- Add a flyer download button to event cards
- Add a calendar export (`.ics`) button
- Restore and redesign the Resources page
- Add a contact form so people don't have to email directly

### Pull Request Process

1. Make your changes in a branch (`git checkout -b my-fix`)
2. Test in a browser on both desktop and mobile (or resize the window)
3. Open a PR against `main` with a short description of what you changed

No special CI setup. If it looks right in the browser, it's ready.

---

## Contact

Questions, corrections, or want to get involved?

📧 [edesoto18@gmail.com](mailto:edesoto18@gmail.com)

Or open an [Issue](https://github.com/eRaWk23/handgame/issues) on GitHub.

---

## License

This project is open source. Fork it, improve it, adapt it for your community.
