# Recensio

A fast, modern Django app for discovering movies and TV shows, reviewing what you watch, and curating personal lists. Recensio emphasizes performance and mobile-first UX with lazy data-fetching from TMDB, year-aware canonical URLs, and lightweight, responsive UI.

### Home
![Home Page](src/app/static/images/site-design-imgs/Home.png)

![Home Page 2](src/app/static/images/site-design-imgs/home2.png)

## Features

- Movie and TV discovery with trending, popular, and filtered browse views
- Rich content detail pages with stats, reviews, and a "Similar" row (TMDB recommendations + similar)
- Personal lists (public/private), likes, and comments
- Reviews with likes; user activity feed and recent reviews on profile
- Follow system with live Follow/Unfollow UI; member directory (Popular This Week, Positive, Negative)
- Click-time redirect to canonical, year-aware slugs via `/go/<type>/<tmdb_id>/`
- Performance-first: defers TMDB lookups to click-time or small JSON endpoints and lazy-hydrates UI
- Mobile UX: compact hero on detail pages, single-column grids on phones, optimized navbar/overlay

## Browse and Lists UI

### Browse
![Browse Page](src/app/static/images/site-design-imgs/browse.png)

### Lists
![Lists Page](src/app/static/images/site-design-imgs/lists.png)

## Tech Stack

- Backend: Django 5.x
- Database: PostgreSQL (psycopg2-binary); a SQLite dev file may exist for local experimentation
- External API: TMDB (The Movie Database)
- Frontend: Django templates, vanilla JS (fetch + IntersectionObserver), Bootstrap-like styling via custom CSS

## Requirements

- Python 3.11+ recommended
- PostgreSQL 13+ (or compatible managed PG service)
- TMDB API key

Install Python packages:

```bash
pip install -r requirements.txt
```

## Configuration

Provide a `.env` file at the project root (same folder as `requirements.txt`) with the following keys:

```bash
# Django
SECRET_KEY=
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (PostgreSQL)
DATABASE_URL=postgres://USER:PASSWORD@HOST:PORT/DBNAME
CONN_MAX_AGE=60

# TMDB
TMDB_API_KEY=your_tmdb_api_key
```

Notes:

- `ALLOWED_HOSTS` in settings.py defaults to localhost/127.0.0.1; override via env if deploying.
- When using SQLite only for quick local smoke tests, you may omit `DATABASE_URL`; otherwise, use Postgres for full features.

## Database schema

This project uses simple SQL tables created on demand by the code path (no migrations in this repo). At minimum, ensure you provide a PostgreSQL database and run the app to allow tables to be created by the data access methods. Core tables include:

- users, content, user_watched, user_ratings, user_rating_likes
- user_lists, list_items, list_likes, list_comments
- user_follows
- user_settings (key/value per user) – created lazily when profile settings are saved

If you prefer migrations, you can backfill a schema later based on the SQL in the data-access functions in `app/content_service.py` and `app/views.py`.

## Running locally

From the `src` directory:

```bash
# 1) Apply environment
# Ensure .env exists at repo root

# 2) Run the Django server
python manage.py runserver
```

Server will start at http://127.0.0.1:8000/ by default.

## Project layout

```
recensio/
├─ requirements.txt
├─ README.md
└─ src/
   ├─ manage.py
   ├─ db.sqlite3                 # Optional local dev DB (not for production)
   └─ app/
      ├─ settings.py             # Django settings (env-driven)
      ├─ urls.py                 # Routes (incl. /go/<type>/<tmdb_id>/ and API endpoints)
      ├─ views.py                # Page views + JSON endpoints (members, similar, profile banner, etc.)
      ├─ content_service.py      # DB data-access and domain helpers (lists, reviews, likes, stats)
      ├─ tmdb_service.py         # TMDB API client (details, images, recs/similar)
      ├─ templates/              # Django templates (home, browse, detail, lists, members, profile)
      └─ static/
         └─ styles.css           # Custom responsive CSS
```

## Key endpoints

- Pages
  - `/` – Home
  - `/browse/` – Discovery page with trending/popular and filters
  - `/movie/<slug>/` – Movie detail page
  - `/tv/<slug>/` – TV show detail page
  - `/list/<username>/<listname>/` – Public list page
  - `/members/` – Members directory
  - `/profile/<username>/` – User profile
- Helpers & API
  - `/go/<type>/<tmdb_id>/` – Click-time redirect to canonical slug (year-aware)
  - `/api/similar/movies/<id>/` and `/api/similar/tv/<id>/` – JSON for Similar rows
  - `/members/recent-art/<user_id>/` – JSON of 5 recent posters for member tiles
  - `/profile/banner/<user_id>/` – JSON to fetch a profile banner image lazily
  - Various POST endpoints for lists, ratings, follows, and comments (see fetch usage in templates)

## Development notes

- Performance: expensive TMDB calls are deferred to click-time redirect or lightweight JSON endpoints; UI then lazy-hydrates.
- Slugs: year-aware slugs keep canonical URLs stable; links use `/go/...` to compute the slug server-side.
- Mobile: detail pages use a compact hero with smaller poster/actions; content grids collapse to one column on phones.
- Security: env-based secrets, CSRF on POSTs via Django decorators, server-side permission checks for list/comment operations.

## Deployment

- Ensure production-ready environment variables in `.env` or platform settings (SECRET_KEY, DEBUG=False, ALLOWED_HOSTS, DATABASE_URL, TMDB_API_KEY).
- Serve static files via your platform (e.g., WhiteNoise, CDN, or web server). This repo doesn’t include a collectstatic config; add one if needed.
- Use a Postgres service and run the Django app via your preferred process manager. Example Procfile process:

```
web: python src/manage.py runserver 0.0.0.0:8000
```

For production, prefer `gunicorn` or an ASGI server (e.g., uvicorn + daphne) and configure static serving appropriately.

## Troubleshooting

- TMDB images/Similar not loading: verify `TMDB_API_KEY` and outbound network access.
- Lists/ratings/follows not updating: confirm DB connectivity and that your database user has write access.
- Canonical slug mismatch: links should navigate via `/go/...`; direct bookmarks to `/movie/<slug>/` or `/tv/<slug>/` still resolve via TMDB title search.

## License

This project is provided as-is under the MIT License. See LICENSE if included, or add one to your fork.
