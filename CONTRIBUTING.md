# Contributing to Handgame Events

Thanks for wanting to help. This project is small, community-maintained, and easy to jump into — whether you know how to code or not.

---

## Ways to Help (no code required)

- **Submit events** at [handgame.info/submission.html](https://www.handgame.info/submission.html)
- **Share the site** with organizers, family, or tribal departments
- **Report a bug** by opening an [Issue](https://github.com/eRaWk23/handgame/issues) — describe what happened and what you expected
- **Suggest a feature** — also an Issue, just tag it "enhancement"
- **Fix a typo or wording** — just open a pull request

---

## Setting Up Locally (takes 2 minutes)

No Node, no npm, no build tools required.

```bash
git clone https://github.com/eRaWk23/handgame.git
cd handgame
open index.html   # Mac
start index.html  # Windows
xdg-open index.html  # Linux
```

The site connects to the live Supabase backend automatically. You'll see real event data.

If you want to test submissions without hitting the live database, contact [edesoto18@gmail.com](mailto:edesoto18@gmail.com) for a dev Supabase project.

---

## Code Style

- Indent with **2 spaces**
- Keep JS vanilla — no frameworks, no build step
- Write accessible HTML: labels on inputs, `alt` on images, `aria-*` where helpful
- Test on mobile (or shrink your browser window to ~375px)
- Dark and light mode both need to look right — check both before submitting

---

## Submitting a Pull Request

1. Fork the repo
2. Create a branch: `git checkout -b fix/my-description`
3. Make your changes
4. Open a PR against `main`
5. Describe what you changed and why

Small PRs are easier to review than big ones. If you're not sure whether something is a good idea, open an Issue first.

---

## Respect

This site exists to support a living cultural tradition. Contributions should treat the game, the people who play it, and the communities involved with respect.
