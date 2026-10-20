# Prime Insurance AI web app

Three working desks built from the PRD and SRD, running on synthetic data:

| Page | Phase | What it does |
|---|---|---|
| `fraud.html` | 1 | Scores claims (rules, peer-group anomalies, network links), queues the riskiest for investigators, saves outcomes as training labels |
| `intake.html` | 2 | Reads first-notice-of-loss emails, checks cover, lists missing documents, routes claims, settles simple ones only when the fraud score allows |
| `reconciliation.html` | 3 | Matches bank lines to premiums and claim payments, auto-clears confident matches, queues the rest, sends payment problems to the fraud team |

**Every claim, email and bank line is invented.** Do not load real policyholder or bank data into this app as it stands: it has no login, no audit trail and no data-protection controls.

## Two ways to host it

| | Vercel | GitHub Pages |
|---|---|---|
| Pages and data | Yes | Yes |
| "Read with Claude" on intake | Yes, with `ANTHROPIC_API_KEY` | No (rules reading only) |
| Decisions shared between users | Yes, with Upstash Redis | No (saved in each browser) |
| Can be made private | Yes (Deployment Protection) | Only on paid GitHub plans |

GitHub Pages serves static files only, so it cannot hold an API key or a shared database. Use it for a demo; use Vercel for anything a team works in.

### Vercel

1. Push this folder to a GitHub repository (it can be the repository root or a subfolder).
2. In Vercel, **Add New → Project**, import the repository. If the app is in a subfolder, set **Root Directory** to it. No build command is needed; `vercel.json` serves `public/` and runs `api/`.
3. **Settings → Environment Variables**: add `ANTHROPIC_API_KEY` to turn on "Read with Claude". Optionally `ANTHROPIC_MODEL` (default `claude-opus-5-5`).
4. **Storage → Upstash Redis** (Marketplace): connect a database to the project. It sets `KV_REST_API_URL` and `KV_REST_API_TOKEN`, and decisions become shared.
5. **Settings → Deployment Protection**: turn on Vercel Authentication (or password protection). Without it, anyone with the URL can write records and spend your Anthropic credit.
6. Redeploy. The top bar of every page says whether shared storage and Claude reading are on.

### GitHub Pages

1. Push this folder as the root of a repository.
2. **Settings → Pages → Source: GitHub Actions**. The workflow in `.github/workflows/pages.yml` rebuilds the pages and publishes `public/` on every push to `main`.
3. The site works without a server: decisions are kept in each browser's local storage and Claude reading is off.

## Run it locally

```bash
npm install                 # only needed for "Read with Claude"
cp .env.example .env        # fill in what you want turned on
node scripts/dev-server.js  # http://localhost:3000
```

Without `.env` values the app runs in the same mode as GitHub Pages. Any static server pointed at `public/` also works (`python3 -m http.server -d public`).

## Rebuild

```bash
python3 scripts/build.py          # rebuild pages from src/ templates
python3 scripts/build.py --data   # regenerate the synthetic data with engine/ first
```

The build uses only the Python standard library. Seeds are fixed, so `--data` gives the same numbers each time.

## Layout

```
api/extract.js      Reads an intake email with Claude (prompt is server-side; key never reaches the browser)
api/records.js      Shared storage for outcomes, decisions and intake records (Redis REST)
engine/             Python data generators, fraud scorer and reconciliation matcher
src/                Desk templates (same ones the claude.ai prototypes use)
scripts/build.py    Builds public/ from src/ and engine/
scripts/dev-server.js  Local server that behaves like Vercel
public/             The site: pages, assets/, data/
```

## Before this goes near real data

- Add sign-in (Vercel Authentication, or SSO in front of it) and tie each saved decision to a named user.
- Keep an append-only audit log of every score, decision and override.
- Agree a data-processing basis for sending claim emails to the Anthropic API, and check retention settings on your account.
- Re-tune the fraud weights and reconciliation thresholds on Prime's own history; the numbers on the home page come from synthetic data.
