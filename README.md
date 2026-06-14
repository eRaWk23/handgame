# Handgame.info

**[handgame.info](https://www.handgame.info)** — A site for sharing and discovering Native American Handgame (Stickgame) events.

Find upcoming events, browse flyers, and submit your own. All in one place, on any device.

---

## What the Site Does

- 📅 Lists **upcoming Handgame events** — expired events auto-hide
- 📅 **Calendar view** — month grid with event dots, click a day to see details
- 🔎 **Search** by location, tribe, or keyword
- 🖼️ **Flyer previews** with tap-to-view full size
- 📤 **Share** individual events via native share or link copy
- 🕰️ **Past events** toggle to browse previous events
- 🚩 **Community reporting** — flag inappropriate events, auto-hidden at 3 reports
- 📄 **Printable view** for posting or sharing at events
- 🌞🌙 Light/Dark mode with earth-tone design
- 📱 Fully mobile-friendly
- 🐢 Lightweight — works on slow connections

---

## How to Submit an Event

1. Go to **[handgame.info/submission.html](https://www.handgame.info/submission.html)**
2. Fill in the event title, date, and location
3. Upload a flyer or paste a link to one
4. Hit Submit — that's it

Events go live immediately. The community can report anything that doesn't belong, and admins can review flagged events.

Rate limited to 3 submissions per hour to prevent spam.

> **Have a flyer saved to your phone?** Just tap *Upload Flyer*, pick the image from your camera roll, and submit. No account needed.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Frontend | HTML + CSS + Vanilla JS |
| Database | [Supabase](https://supabase.com) (PostgreSQL) |
| Flyer storage | Supabase Storage |
| Contact form | [FormSubmit](https://formsubmit.co) |
| Hosting | GitHub Pages |
| Domain | `handgame.info` via CNAME |

No frameworks, no build step. Open the HTML in a browser and it works.

---

## Contributing

This project is open to pull requests. All help is welcome — code, design, bug reports, content.

### Getting Started (no install needed)

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/eRaWk23/handgame.git
cd handgame

# 2. Serve locally
python3 -m http.server 8080

# 3. Open in your browser
# http://localhost:8080
```

The site talks to the live Supabase backend, so you'll see real events right away.

### File Overview

```
handgame/
├── index.html          ← Main events listing + calendar view
├── about.html          ← About the site and the game
├── contact.html        ← Contact form (sends to contact@handgame.info)
├── contact-thanks.html ← Thank you page after form submission
├── submission.html     ← Public event submission form
├── admin.html          ← Admin panel (login required)
├── submission.css      ← Styles specific to the submission page
├── style.css           ← Global styles (earth-tone dark/light mode)
├── script.js           ← Events, calendar, search, reporting, share
├── supabaseClient.js   ← Supabase client setup
├── favicon.svg         ← Tab icon (handgame sticks)
├── CNAME               ← Custom domain config for GitHub Pages
└── handgame.jpeg / handgameCA.jpg / handgameSticks.jpg
```

### Good First Issues

- Fix a typo or improve wording anywhere on the site
- Improve mobile layout or button sizing
- Add a calendar export (`.ics`) button
- Restore and redesign the Resources page
- Light mode color polish

### Pull Request Process

1. Make your changes in a branch (`git checkout -b my-fix`)
2. Test in a browser on both desktop and mobile (or resize the window)
3. Open a PR against `main` with a short description of what you changed

No special CI setup. If it looks right in the browser, it's ready.

---

## Contact

Questions, corrections, or want to get involved?

📧 [contact@handgame.info](mailto:contact@handgame.info)
💬 [Contact form](https://www.handgame.info/contact.html)
🐛 [Open an Issue](https://github.com/eRaWk23/handgame/issues) on GitHub

---

## License

This project is open source. Fork it, improve it, adapt it for your community.
