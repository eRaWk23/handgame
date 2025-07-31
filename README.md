# Handgame Events Site

A lightweight, community-powered site to share and discover Native American Handgame events. Built for speed, simplicity, and accessibility on all devices.

## 🌐 Website Features

- 📅 Displays upcoming Handgame events only
- 🔎 Search by location, tribe, or keywords
- 🖼️ Flyer preview
- ⛔ Auto-hides expired events and flags flyers older than 30 days
- 🔄 Pagination for smoother browsing
- 📄 Print-friendly layout
- 🌞 Light/Dark mode toggle
- 📱 Fully mobile-responsive
- 🧠 Powered by Supabase (database + file storage)
- 🔒 Admin-only event uploads through custom secure form
- ⚙️ Resources page temporarily disabled for redesign

## 🧩 Tech Stack

- HTML + CSS + JavaScript
- Supabase (PostgreSQL + Storage + API)
- GitHub Pages (hosting)

## ⚙️ How It Works

1. Contributors submit events via a custom upload form
2. Events are stored in Supabase (along with flyers in Supabase Storage)
3. The site pulls event data dynamically via Supabase JavaScript SDK
4. Expired events are hidden automatically; old flyers flagged
5. The interface updates in real-time with pagination and search

## 🤝 Contributing

This project is open to pull requests!  
Fork the repo → make changes → submit a PR.

All suggestions, bug fixes, and features are welcome.

## 📫 Contact

For questions or contributor access, email [edesoto18@gmail.com](mailto:edesoto18@gmail.com)

