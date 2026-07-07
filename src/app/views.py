import os
import re
from django.shortcuts import render, redirect
from django.db import connection
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.http import JsonResponse
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
import base64
import json
from .tmdb_service import TMDBService
from .content_service import (
    enrich_content_with_stats,
    get_content_stats,
    mark_as_watched,
    has_user_watched,
    add_rating,
    get_content_reviews,
    get_recently_reviewed_content,
    get_user_lists,
    create_user_list,
    add_to_list,
    remove_from_list,
    verify_user_owns_list,
    get_user_by_username as cs_get_user_by_username,
    get_list_by_user_and_name,
    get_list_items,
    toggle_like_list,
    add_list_comment,
    get_list_comments,
    get_popular_lists,
    get_recent_list_items,
    get_list_item_counts,
    get_top_lists_by_engagement,
    get_popular_reviews,
    search_lists,
    delete_list_comment,
    has_user_rated,
    toggle_like_review,
    get_user_top_rated_content,
    get_user_recent_activity,
    get_user_recent_reviews,
)

# --- Simple user settings storage helpers ---
def get_user_settings(user_id: int) -> dict:
    """Return dict of user settings. Uses a simple key/value table user_settings(key TEXT, value TEXT)."""
    try:
        with connection.cursor() as cursor:
            # Ensure table exists lazily
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    PRIMARY KEY (user_id, key)
                )
            """)
            cursor.execute("SELECT key, value FROM user_settings WHERE user_id = %s", [user_id])
            rows = cursor.fetchall() or []
            out = { k: v for (k, v) in rows }
            return out
    except Exception:
        return {}

def set_user_settings(user_id: int, updates: dict) -> None:
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    PRIMARY KEY (user_id, key)
                )
            """)
            for k, v in updates.items():
                cursor.execute(
                    "INSERT INTO user_settings(user_id, key, value) VALUES (%s, %s, %s)\n"
                    "ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value",
                    [user_id, k, str(v)],
                )
    except Exception:
        pass

def slugify_title(title, year=None):
    """Convert title and year to URL slug format"""
    # Remove special characters and convert to lowercase
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    # Replace spaces with hyphens

    slug = re.sub(r'[-\s]+', '-', slug).strip('-')
    # Add year if provided
    if year:
        slug = f"{slug}-{year}"
    return slug
def go_to_content(request, media_type, tmdb_id: int):
    """Redirect to canonical detail URL for content using TMDB details to form year-aware slug.
    This avoids fetching TMDB during list/grid renders; we only fetch on click.
    """
    tmdb = TMDBService()
    title = ''
    year = ''
    try:
        if media_type == 'tv':
            det = tmdb.get_tv_details(tmdb_id)
            if det:
                title = det.get('name') or ''
                year = (det.get('first_air_date') or '')[:4]
        else:
            det = tmdb.get_movie_details(tmdb_id)
            if det:
                title = det.get('title') or ''
                year = (det.get('release_date') or '')[:4]
    except Exception:
        pass
    slug = slugify_title(title or str(tmdb_id), year if year else None)
    if media_type == 'tv':
        return HttpResponseRedirect(f"/tv/{slug}/")
    return HttpResponseRedirect(f"/movie/{slug}/")

def profile_banner(request, user_id: int):
    """Return backdrop URL for the user's top favorite item (first of top_five), computed lazily.
    Response: { success, backdrop_url?: str }
    """
    try:
        tmdb = TMDBService()
        # Reuse domain logic to get top favorites quickly
        top_five = get_user_top_rated_content(user_id, limit=1)
        if not top_five:
            return JsonResponse({ 'success': True, 'backdrop_url': None })
        item = top_five[0]
        media_type = item.get('media_type', 'movie')
        tmdb_id = item.get('tmdb_id')
        backdrop_url = None
        try:
            if media_type == 'tv':
                det = tmdb.get_tv_details(tmdb_id)
                if det and det.get('backdrop_path'):
                    backdrop_url = tmdb.get_backdrop_url(det.get('backdrop_path'))
            else:
                det = tmdb.get_movie_details(tmdb_id)
                if det and det.get('backdrop_path'):
                    backdrop_url = tmdb.get_backdrop_url(det.get('backdrop_path'))
        except Exception:
            backdrop_url = None
        return JsonResponse({ 'success': True, 'backdrop_url': backdrop_url })
    except Exception as e:
        return JsonResponse({ 'success': False, 'error': str(e) }, status=500)

def similar_movies(request, movie_id: int):
    """Return JSON list of similar/recommended movies for the given movie_id."""
    try:
        tmdb = TMDBService()
        out = []
        seen = set()
        # Prefer recommendations, then similar
        try:
            recs = tmdb.get_movie_recommendations(movie_id) or {}
            for r in (recs.get('results') or []):
                mid = r.get('id')
                if not mid or mid in seen or mid == movie_id:
                    continue
                seen.add(mid)
                out.append({
                    'tmdb_id': mid,
                    'media_type': 'movie',
                    'title': r.get('title') or r.get('original_title') or '',
                    'poster_url': tmdb.get_poster_url(r.get('poster_path')),
                    'go_url': f"/go/movie/{mid}/",
                    'popularity': r.get('popularity') or 0,
                })
        except Exception:
            pass
        try:
            sim = tmdb.get_movie_similar(movie_id) or {}
            for r in (sim.get('results') or []):
                mid = r.get('id')
                if not mid or mid in seen or mid == movie_id:
                    continue
                seen.add(mid)
                out.append({
                    'tmdb_id': mid,
                    'media_type': 'movie',
                    'title': r.get('title') or r.get('original_title') or '',
                    'poster_url': tmdb.get_poster_url(r.get('poster_path')),
                    'go_url': f"/go/movie/{mid}/",
                    'popularity': r.get('popularity') or 0,
                })
        except Exception:
            pass
        # Filter out those without posters for a clean strip
        out = [o for o in out if o.get('poster_url')]
        # Sort by popularity desc and cap
        out.sort(key=lambda x: x.get('popularity') or 0, reverse=True)
        out = out[:20]
        return JsonResponse({ 'success': True, 'items': out })
    except Exception as e:
        return JsonResponse({ 'success': False, 'error': str(e) }, status=500)

def similar_tv(request, tv_id: int):
    """Return JSON list of similar/recommended TV shows for the given tv_id."""
    try:
        tmdb = TMDBService()
        out = []
        seen = set()
        try:
            recs = tmdb.get_tv_recommendations(tv_id) or {}
            for r in (recs.get('results') or []):
                tid = r.get('id')
                if not tid or tid in seen or tid == tv_id:
                    continue
                seen.add(tid)
                out.append({
                    'tmdb_id': tid,
                    'media_type': 'tv',
                    'title': r.get('name') or r.get('original_name') or '',
                    'poster_url': tmdb.get_poster_url(r.get('poster_path')),
                    'go_url': f"/go/tv/{tid}/",
                    'popularity': r.get('popularity') or 0,
                })
        except Exception:
            pass
        try:
            sim = tmdb.get_tv_similar(tv_id) or {}
            for r in (sim.get('results') or []):
                tid = r.get('id')
                if not tid or tid in seen or tid == tv_id:
                    continue
                seen.add(tid)
                out.append({
                    'tmdb_id': tid,
                    'media_type': 'tv',
                    'title': r.get('name') or r.get('original_name') or '',
                    'poster_url': tmdb.get_poster_url(r.get('poster_path')),
                    'go_url': f"/go/tv/{tid}/",
                    'popularity': r.get('popularity') or 0,
                })
        except Exception:
            pass
        out = [o for o in out if o.get('poster_url')]
        out.sort(key=lambda x: x.get('popularity') or 0, reverse=True)
        out = out[:20]
        return JsonResponse({ 'success': True, 'items': out })
    except Exception as e:
        return JsonResponse({ 'success': False, 'error': str(e) }, status=500)

def members_recent_art(request, user_id: int):
    """Return up to 5 of a user's recent reviewed/watched items with poster urls and click-through go links."""
    try:
        tmdb = TMDBService()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH items AS (
                  SELECT ur.user_id, c.tmdb_id, c.media_type, c.title, c.poster_path, ur.updated_at AS ts
                  FROM user_ratings ur
                  JOIN content c ON c.id = ur.content_id
                  WHERE ur.user_id = %s AND ur.review_text IS NOT NULL
                  UNION ALL
                  SELECT uw.user_id, c.tmdb_id, c.media_type, c.title, c.poster_path, uw.watched_at AS ts
                  FROM user_watched uw
                  JOIN content c ON c.id = uw.content_id
                  WHERE uw.user_id = %s
                ), ranked AS (
                  SELECT *, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY ts DESC) rn FROM items
                )
                SELECT tmdb_id, media_type, title, poster_path
                FROM ranked
                WHERE rn <= 5
                ORDER BY rn
                """,
                [user_id, user_id],
            )
            rows = cursor.fetchall() or []
            items = []
            for tmdb_id, media_type, title, poster_path in rows:
                items.append({
                    'tmdb_id': tmdb_id,
                    'media_type': media_type,
                    'title': title,
                    'poster_url': tmdb.get_poster_url(poster_path),
                    'go_url': f"/go/{media_type}/{tmdb_id}/",
                })
            return JsonResponse({ 'success': True, 'items': items })
    except Exception as e:
        return JsonResponse({ 'success': False, 'error': str(e) }, status=500)

def read_image_as_bytea(image_path):
    with open(image_path, 'rb') as file:
        return file.read()

def get_user_by_username(username):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, username, password, firstname, lastname, pfp FROM users WHERE username = %s",
            [username]
        )
        result = cursor.fetchone()
        if result:
            return {
                'id': result[0],
                'username': result[1],
                'password': result[2],
                'firstname': result[3],
                'lastname': result[4],
                'pfp': base64.b64encode(result[5]).decode() if result[5] else None
            }
        return None

def validate_password(password):
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not password[0].isupper():
        return False, "Password must start with a capital letter"
    return True, None

def register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        firstname = request.POST.get('firstname')
        lastname = request.POST.get('lastname')
        email = request.POST.get('email')

        # Validate password
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            messages.error(request, error_msg)
            return redirect('home')

        # Check if username exists
        if get_user_by_username(username):
            messages.error(request, 'Username already exists')
            return redirect('home')

        # Check if email exists
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE email = %s", [email])
            if cursor.fetchone():
                messages.error(request, 'Email already exists')
                return redirect('home')

        # Hash password using Django's make_password
        hashed_password = make_password(password)

        # Get default profile picture
        pfp_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'pfp-basic.jpg')
        pfp_data = read_image_as_bytea(pfp_path)

        # Insert new user
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO users (firstname, lastname, username, email, password, pfp)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, [firstname, lastname, username, email, hashed_password, pfp_data])
            user_id = cursor.fetchone()[0]

        # Store user info in session
        request.session['user_id'] = user_id
        request.session['username'] = username
        request.session['pfp'] = base64.b64encode(pfp_data).decode()

        messages.success(request, 'Registration successful!')
        return redirect('home')

def login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, password, firstname, lastname, pfp FROM users WHERE username = %s",
                [username]
            )
            user_data = cursor.fetchone()

        if user_data:
            user_id = user_data[0]
            hashed_password = user_data[2]
            pfp = user_data[5]

            # Check if the provided password matches the hashed password
            if check_password(password, hashed_password):
                request.session['user_id'] = user_id
                request.session['username'] = username
                request.session['pfp'] = base64.b64encode(pfp).decode() if pfp else None
                messages.success(request, 'Login successful!')
            else:
                messages.error(request, 'Invalid username or password')
        else:
            messages.error(request, 'Invalid username or password')

        return redirect('home')

def logout(request):
    request.session.flush()
    return redirect('home')

def about(request):
    return render(request, 'about.html')

def home(request):
    tmdb = TMDBService()
    
    # Get recently reviewed content (already includes stats)
    recently_reviewed = get_recently_reviewed_content(limit=9)
    
    # Enrich with poster URLs and go_url for click-time redirect
    for item in recently_reviewed:
        item['poster_url'] = tmdb.get_poster_url(item.get('poster_path'))
        media_type = item.get('media_type', 'movie')
        item['go_url'] = f"/go/{media_type}/{item.get('tmdb_id')}/"
    
    # annotate per-user flags if logged in
    user_id = request.session.get('user_id')
    if user_id:
        for item in recently_reviewed:
            try:
                item['watched_by_me'] = has_user_watched(user_id, item.get('tmdb_id'), item.get('media_type'))
                item['reviewed_by_me'] = has_user_rated(user_id, item.get('tmdb_id'), item.get('media_type'))
            except Exception:
                item['watched_by_me'] = False
                item['reviewed_by_me'] = False

    # Popular lists for homepage (top by engagement = likes + comments)
    popular_lists_home = get_top_lists_by_engagement(limit=6)
    # Enrich with recent items (for collage), counts, and detail URLs
    for pl in popular_lists_home:
        try:
            items = get_recent_list_items(pl['id'], limit=5)
            for it in items:
                it['poster_url'] = tmdb.get_poster_url(it.get('poster_path'))
            pl['recent_items'] = items
            counts = get_list_item_counts(pl['id'])
            pl['item_counts'] = counts
            pl['detail_url'] = f"/list/{pl['username']}/{pl['name'].replace(' ', '-').lower()}/"
        except Exception:
            pl['recent_items'] = []
            pl['item_counts'] = {'movies': 0, 'shows': 0}

    # Popular reviews (sitewide)
    popular_reviews = get_popular_reviews(limit=5, current_user_id=request.session.get('user_id'))
    # Enrich with poster urls and click-time redirect URL
    for r in popular_reviews:
        try:
            r['poster_url'] = tmdb.get_poster_url(r.get('poster_path'))
            media_type_r = r.get('media_type', 'movie')
            r['go_url'] = f"/go/{media_type_r}/{r.get('tmdb_id')}/"
        except Exception:
            r['poster_url'] = None
            r['go_url'] = '#'

    return render(request, 'home.html', {
        'recently_reviewed': recently_reviewed,
        'popular_lists_home': popular_lists_home,
        'popular_reviews': popular_reviews,
    })

@require_POST
def update_avatar(request):
    """Accept a base64 data URL (PNG/JPEG) of the cropped avatar and save to the user's pfp."""
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({ 'success': False, 'error': 'Not authenticated' }, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
        data_url = payload.get('image_data')
        if not data_url or ',' not in data_url:
            return JsonResponse({ 'success': False, 'error': 'Invalid image data' }, status=400)

        header, b64data = data_url.split(',', 1)
        # Basic size guard: ~2MB max
        if len(b64data) > 3_000_000:
            return JsonResponse({ 'success': False, 'error': 'Image too large' }, status=413)

        image_bytes = base64.b64decode(b64data)

        # Persist to DB
        with connection.cursor() as cursor:
            cursor.execute("UPDATE users SET pfp = %s WHERE id = %s", [image_bytes, user_id])

        # Update session avatar (store base64 without prefix like elsewhere)
        request.session['pfp'] = base64.b64encode(image_bytes).decode('utf-8')

        return JsonResponse({ 'success': True, 'pfp': request.session['pfp'] })
    except Exception as e:
        return JsonResponse({ 'success': False, 'error': str(e) }, status=500)

def browse(request):
    tmdb = TMDBService()
    
    # Get filter parameters from request
    year = request.GET.get('year')
    min_rating = request.GET.get('rating')
    sort_by = request.GET.get('sort')
    genre_id = request.GET.get('genre')
    media_type = request.GET.get('type')  # 'movie' or 'tv'
    search_query = request.GET.get('search')
    page = int(request.GET.get('page', 1))  # Get current page, default to 1
    
    # If search query provided, use search endpoint
    if search_query:
        search_results = tmdb.search_multi(search_query)
        results = []
        if search_results and 'results' in search_results:
            for item in search_results['results'][:20]:
                # Only include movies and TV shows, skip people/actors
                item_media_type = item.get('media_type', '')
                if item_media_type not in ['movie', 'tv']:
                    continue
                    
                item['poster_url'] = tmdb.get_poster_url(item.get('poster_path'))
                # Add detail page URL
                if item_media_type == 'tv':
                    title = item.get('name', '')
                    year = item.get('first_air_date', '')[:4]
                else:
                    title = item.get('title', '')
                    year = item.get('release_date', '')[:4]
                slug = slugify_title(title, year)
                item['detail_url'] = f"/{item_media_type}/{slug}/"
                results.append(item)
        
        # Enrich with custom stats
        results = enrich_content_with_stats(results)
        # Annotate user flags
        user_id = request.session.get('user_id')
        if user_id:
            for it in results:
                try:
                    it['watched_by_me'] = has_user_watched(user_id, it.get('id'), it.get('media_type'))
                    it['reviewed_by_me'] = has_user_rated(user_id, it.get('id'), it.get('media_type'))
                except Exception:
                    it['watched_by_me'] = False
                    it['reviewed_by_me'] = False
        
        context = {
            'results': results,
            'search_query': search_query,
            'active_filters': {'search': search_query}
        }
        return render(request, 'browse.html', context)
    
    # Build active filters dict for display
    active_filters = {}
    if year:
        active_filters['year'] = year
    # Rating and sort filters removed from UI, do not surface them in active_filters
    if genre_id:
        active_filters['genre'] = genre_id
    if media_type:
        active_filters['type'] = media_type
    
    # Determine TMDB sort parameter
    tmdb_sort = 'popularity.desc'
    if sort_by == 'top_rated':
        tmdb_sort = 'vote_average.desc'
    elif sort_by == 'new':
        tmdb_sort = 'release_date.desc'
    
    # If filters are applied (including just media type), use discover endpoint
    if year or min_rating or genre_id or sort_by or media_type:
        filtered_results = []
        total_pages = 1
        total_results = 0

        # If no media type specified, default to movies to avoid double API calls
        if not media_type:
            media_type = 'movie'

        if media_type == 'tv':
            # Use correct TV sort when 'new' is chosen
            tv_sort = 'first_air_date.desc' if sort_by == 'new' else tmdb_sort

            # Map movie genre ids to TV genre ids (TMDB differs between movie & TV)
            # Example mappings:
            #  - 878 (Sci-Fi movie) -> 10765 (Sci-Fi & Fantasy TV)
            #  - 14 (Fantasy movie) -> 10765 (Sci-Fi & Fantasy TV)
            #  - 12 (Adventure) / 28 (Action) -> 10759 (Action & Adventure TV)
            #  - 53 (Thriller) -> 9648 (Mystery TV)
            #  - 10752 (War) -> 10768 (War & Politics TV)
            movie_to_tv_genre = {
                '878': '10765',
                '14': '10765',
                '12': '10759',
                '28': '10759',
                '53': '9648',
                '10752': '10768',
            }

            tv_genre_param = None
            tv_without = None
            if genre_id is not None:
                g = str(genre_id)
                if g == '27':
                    # Horror in TV: approximate with OR of dark genres and exclude obviously non-horror ones
                    tv_genre_param = '9648|10765'
                    # Exclude Animation, Comedy, Family, Kids, Reality, Soap, Talk, News, Documentary
                    tv_without = '16,35,10751,10762,10764,10766,10767,10763,99'
                elif g in movie_to_tv_genre:
                    tv_genre_param = movie_to_tv_genre[g]
                else:
                    tv_genre_param = g

            tv_data = tmdb.discover_tv(
                year=year,
                min_rating=min_rating,
                genre_id=tv_genre_param,
                sort_by=tv_sort,
                page=page,
                without_genres=tv_without
            )
            if tv_data and 'results' in tv_data:
                total_pages = min(tv_data.get('total_pages', 1), 500)  # TMDB limits to 500 pages
                total_results = tv_data.get('total_results', 0)
                for item in tv_data['results']:
                    item['poster_url'] = tmdb.get_poster_url(item.get('poster_path'))
                    item['media_type'] = 'tv'
                    # Add detail URL
                    title = item.get('name', '')
                    year_item = item.get('first_air_date', '')[:4]
                    slug = slugify_title(title, year_item)
                    item['detail_url'] = f"/tv/{slug}/"
                    filtered_results.append(item)

            # No title-search fallback; results are driven by TV genres only

        elif media_type == 'movie':
            # Discover movies - 1 API call
            movie_data = tmdb.discover_movies(year=year, min_rating=min_rating, genre_id=genre_id, sort_by=tmdb_sort, page=page)
            if movie_data and 'results' in movie_data:
                total_pages = min(movie_data.get('total_pages', 1), 500)  # TMDB limits to 500 pages
                total_results = movie_data.get('total_results', 0)
                for item in movie_data['results']:
                    item['poster_url'] = tmdb.get_poster_url(item.get('poster_path'))
                    item['media_type'] = 'movie'
                    # Add detail URL
                    title = item.get('title', '')
                    year_item = item.get('release_date', '')[:4]
                    slug = slugify_title(title, year_item)
                    item['detail_url'] = f"/movie/{slug}/"
                    filtered_results.append(item)
        
        filtered_results = enrich_content_with_stats(filtered_results)
        # Annotate user flags
        user_id = request.session.get('user_id')
        if user_id:
            for it in filtered_results:
                try:
                    it['watched_by_me'] = has_user_watched(user_id, it.get('id'), it.get('media_type'))
                    it['reviewed_by_me'] = has_user_rated(user_id, it.get('id'), it.get('media_type'))
                except Exception:
                    it['watched_by_me'] = False
                    it['reviewed_by_me'] = False
        
        context = {
            'results': filtered_results,
            'has_filters': True,
            'active_filters': active_filters,
            'current_page': page,
            'total_pages': total_pages,
            'total_results': total_results,
        }
        return render(request, 'browse.html', context)
    
    # Default: show trending, popular movies, and popular TV (no filters)
    trending = []
    popular_movies = []
    popular_tv = []
    
    if sort_by == 'trending' or not any([year, min_rating, genre_id, sort_by, media_type]):
        trending_data = tmdb.get_trending('all', 'week', page=1)
        if trending_data and 'results' in trending_data:
            for item in trending_data['results'][:12]:
                item['poster_url'] = tmdb.get_poster_url(item.get('poster_path'))
                item['backdrop_url'] = tmdb.get_backdrop_url(item.get('backdrop_path'))
                # Add detail URL
                media_type_item = item.get('media_type', 'movie')
                if media_type_item == 'tv':
                    title = item.get('name', '')
                    year_item = item.get('first_air_date', '')[:4]
                else:
                    title = item.get('title', '')
                    year_item = item.get('release_date', '')[:4]
                slug = slugify_title(title, year_item)
                item['detail_url'] = f"/{media_type_item}/{slug}/"
                trending.append(item)
        trending = enrich_content_with_stats(trending)
    
    if media_type == 'tv' or not media_type:
        popular_tv_data = tmdb.get_popular_tv(page=1)
        if popular_tv_data and 'results' in popular_tv_data:
            for item in popular_tv_data['results'][:12]:
                item['poster_url'] = tmdb.get_poster_url(item.get('poster_path'))
                item['media_type'] = 'tv'
                # Add detail URL
                title = item.get('name', '')
                year_item = item.get('first_air_date', '')[:4]
                slug = slugify_title(title, year_item)
                item['detail_url'] = f"/tv/{slug}/"
                popular_tv.append(item)
        popular_tv = enrich_content_with_stats(popular_tv)
    
    if media_type == 'movie' or not media_type:
        popular_movies_data = tmdb.get_popular_movies(page=1)
        if popular_movies_data and 'results' in popular_movies_data:
            for item in popular_movies_data['results'][:12]:
                item['poster_url'] = tmdb.get_poster_url(item.get('poster_path'))
                item['media_type'] = 'movie'
                # Add detail URL
                title = item.get('title', '')
                year_item = item.get('release_date', '')[:4]
                slug = slugify_title(title, year_item)
                item['detail_url'] = f"/movie/{slug}/"
                popular_movies.append(item)
        popular_movies = enrich_content_with_stats(popular_movies)
    
    # Annotate user flags for default sections
    user_id = request.session.get('user_id')
    if user_id:
        for it in trending:
            try:
                it['watched_by_me'] = has_user_watched(user_id, it.get('id'), it.get('media_type'))
                it['reviewed_by_me'] = has_user_rated(user_id, it.get('id'), it.get('media_type'))
            except Exception:
                it['watched_by_me'] = False
                it['reviewed_by_me'] = False
        for it in popular_movies:
            try:
                it['watched_by_me'] = has_user_watched(user_id, it.get('id'), 'movie')
                it['reviewed_by_me'] = has_user_rated(user_id, it.get('id'), 'movie')
            except Exception:
                it['watched_by_me'] = False
                it['reviewed_by_me'] = False
        for it in popular_tv:
            try:
                it['watched_by_me'] = has_user_watched(user_id, it.get('id'), 'tv')
                it['reviewed_by_me'] = has_user_rated(user_id, it.get('id'), 'tv')
            except Exception:
                it['watched_by_me'] = False
                it['reviewed_by_me'] = False

    context = {
        'trending': trending,
        'popular_movies': popular_movies,
        'popular_tv': popular_tv,
        'active_filters': active_filters,
    }
    
    return render(request, 'browse.html', context)   

def lists(request):
    q = request.GET.get('q', '').strip()
    user_lists = []
    username = request.session.get('username')
    if 'user_id' in request.session:
        try:
            user_lists = get_user_lists(request.session['user_id'])
        except Exception:
            user_lists = []
    # Enrich Your Lists with recent items and poster URLs
    tmdb = TMDBService()
    for l in user_lists:
        try:
            items = get_recent_list_items(l['id'], limit=5)
            for it in items:
                it['poster_url'] = tmdb.get_poster_url(it.get('poster_path'))
            l['recent_items'] = items
        except Exception:
            l['recent_items'] = []

    # Popular public lists (second section)
    popular = get_popular_lists(limit=12)
    # Enrich with recent items (5) and poster URLs, plus counts and detail URL
    for pl in popular:
        items = get_recent_list_items(pl['id'], limit=5)
        for it in items:
            it['poster_url'] = tmdb.get_poster_url(it.get('poster_path'))
        pl['recent_items'] = items
        counts = get_list_item_counts(pl['id'])
        pl['item_counts'] = counts
        pl['detail_url'] = f"/list/{pl['username']}/{pl['name'].replace(' ', '-').lower()}/"

    # Optional: search lists
    search_results = []
    if q:
        viewer_id = request.session.get('user_id')
        search_results = search_lists(q, viewer_user_id=viewer_id, limit=24, offset=0)
        # Enrich search results similar to popular lists
        for sl in search_results:
            items = get_recent_list_items(sl['id'], limit=5)
            for it in items:
                it['poster_url'] = tmdb.get_poster_url(it.get('poster_path'))
            sl['recent_items'] = items
            counts = get_list_item_counts(sl['id'])
            sl['item_counts'] = counts
            sl['detail_url'] = f"/list/{sl['username']}/{sl['name'].replace(' ', '-').lower()}/"

    context = {
        'lists': user_lists,
        'popular_lists': popular,
        'search_results': search_results,
        'q': q,
        'is_logged_in': 'user_id' in request.session,
        'username': username,
    }
    return render(request, 'lists.html', context)


@require_POST
def fetch_user_lists(request):
    """Return the current user's lists (optionally filtered by is_public)."""
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)

    try:
        data = json.loads(request.body or '{}')
        is_public = data.get('is_public')
        if is_public is not None:
            is_public = bool(is_public)

        user_id = request.session['user_id']
        lists = get_user_lists(user_id, is_public)
        return JsonResponse({'success': True, 'lists': lists})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def create_list_view(request):
    """Create a new list for the current user."""
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)

    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        description = data.get('description')
        is_public = bool(data.get('is_public', True))

        new_list = create_user_list(request.session['user_id'], name, description, is_public)
        return JsonResponse({'success': True, 'list': new_list})
    except ValueError as ve:
        return JsonResponse({'success': False, 'error': str(ve)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def add_to_list_view(request):
    """Add a movie/show to an existing user list."""
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)

    try:
        data = json.loads(request.body)
        list_id = data.get('list_id')
        tmdb_id = data.get('tmdb_id')
        media_type = data.get('media_type')
        title = data.get('title')
        poster_path = data.get('poster_path')

        if not all([list_id, tmdb_id, media_type, title]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'}, status=400)

        # Ensure the list belongs to current user
        if not verify_user_owns_list(request.session['user_id'], list_id):
            return JsonResponse({'success': False, 'error': 'Unauthorized list access'}, status=403)

        add_to_list(list_id, tmdb_id, media_type, title, poster_path)

        # Optionally return updated stats
        stats = get_content_stats(tmdb_id, media_type)
        return JsonResponse({'success': True, 'stats': stats})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def remove_from_list_view(request):
    """Remove a movie/show from one of the current user's lists."""
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)

    try:
        data = json.loads(request.body)
        list_id = data.get('list_id')
        tmdb_id = data.get('tmdb_id')
        media_type = data.get('media_type')

        if not all([list_id, tmdb_id, media_type]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'}, status=400)

        if not verify_user_owns_list(request.session['user_id'], list_id):
            return JsonResponse({'success': False, 'error': 'Unauthorized list access'}, status=403)

        result = remove_from_list(list_id, tmdb_id, media_type)
        return JsonResponse({'success': True, **result})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def members(request):
    q = (request.GET.get('q') or '').strip()
    tmdb = TMDBService()
    # Base fetch helper to avoid dup
    def fetch_users(order_clause: str, where_extra: str = '', params: list | tuple = ()):
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    f"""
                    SELECT u.id, u.username, u.firstname, u.lastname, u.pfp,
                           COALESCE(u.followers_count, 0) AS followers,
                           (
                               SELECT COUNT(*) FROM user_ratings ur
                               WHERE ur.user_id = u.id AND (ur.review_text IS NOT NULL AND ur.review_text <> '')
                           ) AS reviews,
                           (
                               SELECT AVG(ur2.score) FROM user_ratings ur2 WHERE ur2.user_id = u.id
                           ) AS avg_score,
                           (
                               SELECT COUNT(*) FROM user_ratings ur3 WHERE ur3.user_id = u.id AND ur3.updated_at >= NOW() - INTERVAL '7 days'
                           ) AS reviews_week
                    FROM users u
                    {('WHERE ' + where_extra) if where_extra else ''}
                    {order_clause}
                    """,
                    params,
                )
                return cursor.fetchall() or []
            except Exception:
                cursor.execute(
                    f"""
                    SELECT u.id, u.username, u.firstname, u.lastname, u.pfp,
                           (SELECT COUNT(*) FROM user_follows f WHERE f.followee_id = u.id) AS followers,
                           (SELECT COUNT(*) FROM user_ratings ur WHERE ur.user_id = u.id AND (ur.review_text IS NOT NULL AND ur.review_text <> '')) AS reviews,
                           (SELECT AVG(ur2.score) FROM user_ratings ur2 WHERE ur2.user_id = u.id) AS avg_score,
                           (SELECT COUNT(*) FROM user_ratings ur3 WHERE ur3.user_id = u.id AND ur3.updated_at >= NOW() - INTERVAL '7 days') AS reviews_week
                    FROM users u
                    {('WHERE ' + where_extra) if where_extra else ''}
                    {order_clause}
                    """,
                    params,
                )
                return cursor.fetchall() or []

    def shape(rows):
        out = []
        for r in rows:
            out.append({
                'id': r[0], 'username': r[1], 'firstname': r[2], 'lastname': r[3],
                'pfp': base64.b64encode(r[4]).decode() if r[4] else None,
                'followers': r[5] or 0,
                'reviews': r[6] or 0,
                'avg_score': float(r[7]) if len(r) > 7 and r[7] is not None else None,
                'reviews_week': r[8] if len(r) > 8 and r[8] is not None else 0,
            })
        return out

    where = []
    params: list = []
    if q:
        where.append("LOWER(u.username) LIKE LOWER(%s)")
        params.append('%' + q + '%')
    where_clause = ' AND '.join(where)

    # If searching, return a single flat result set and skip sections
    if q:
        results_rows = fetch_users("ORDER BY followers DESC, reviews DESC, u.username ASC", where_clause, params)
        results = shape(results_rows)
    # No per-user artwork computation here; fetched lazily via /members/recent-art/<user_id>/

        context = {
            'q': q,
            'search_results': results,
        }
        return render(request, 'members.html', context)

    # Sections (no search)
    top_all_rows = fetch_users("ORDER BY followers DESC, reviews DESC, u.username ASC")
    week_rows = fetch_users("ORDER BY reviews_week DESC, followers DESC, u.username ASC")
    positive_rows = fetch_users("ORDER BY avg_score DESC NULLS LAST, reviews DESC, followers DESC")
    negative_rows = fetch_users("ORDER BY avg_score ASC NULLS LAST, reviews DESC, followers DESC")

    members_week = shape(week_rows[:12])
    members_positive = shape(positive_rows[:12])
    members_negative = shape(negative_rows[:12])

    # No per-user artwork computation for sections; fetched lazily on the client

    context = {
        'q': q,
        'members_week': members_week,
        'members_positive': members_positive,
        'members_negative': members_negative,
    }
    return render(request, 'members.html', context)

@ensure_csrf_cookie
def profile(request, username):
    # Get user profile data
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, username, firstname, lastname, email, pfp 
            FROM users 
            WHERE LOWER(username) = LOWER(%s)
        """, [username])
        user_data = cursor.fetchone()
    
    if not user_data:
        # Avoid noisy flash; return a soft 404 page
        return render(request, 'members.html', status=404)
    
    profile_user = {
        'id': user_data[0],
        'username': user_data[1],
        'firstname': user_data[2],
        'lastname': user_data[3],
        'email': user_data[4],
        'pfp': base64.b64encode(user_data[5]).decode() if user_data[5] else None
    }
    
    # Check if viewing own profile
    is_own_profile = request.session.get('username') == username
    # Load user settings (e.g., hide_fullname)
    settings = get_user_settings(profile_user['id']) if profile_user else {}
    
    # Build sections (no TMDB detail calls during render)
    tmdb = TMDBService()
    profile_banner_url = None  # Provided via lazy endpoint to avoid initial TMDB calls
    top_five = get_user_top_rated_content(profile_user['id'], limit=5)
    for it in top_five:
        it['poster_url'] = tmdb.get_poster_url(it.get('poster_path'))
        media_type = it.get('media_type', 'movie')
        # Click-time redirect computes canonical slug
        it['go_url'] = f"/go/{media_type}/{it.get('tmdb_id')}/"

    recent_activity = get_user_recent_activity(profile_user['id'], limit=5)
    for ev in recent_activity:
        ev['poster_url'] = tmdb.get_poster_url(ev.get('poster_path'))
        media_type = ev.get('media_type', 'movie')
        ev['go_url'] = f"/go/{media_type}/{ev.get('tmdb_id')}/"

    recent_reviews = get_user_recent_reviews(profile_user['id'], limit=5)
    for rr in recent_reviews:
        rr['poster_url'] = tmdb.get_poster_url(rr.get('poster_path'))
        media_type = rr.get('media_type', 'movie')
        rr['go_url'] = f"/go/{media_type}/{rr.get('tmdb_id')}/"

    # For Lists tab
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, name, description, is_public, likes_count, comments_count, updated_at
            FROM user_lists
            WHERE user_id = %s
            ORDER BY updated_at DESC
        """, [profile_user['id']])
        rows = cursor.fetchall() or []
        all_lists = [
            {
                'id': r[0], 'name': r[1], 'description': r[2], 'is_public': bool(r[3]),
                'likes_count': r[4] or 0, 'comments_count': r[5] or 0, 'updated_at': r[6]
            } for r in rows
        ]
    lists_count = len(all_lists)
    for pl in all_lists:
        try:
            items = get_recent_list_items(pl['id'], limit=5)
            for it in items:
                it['poster_url'] = tmdb.get_poster_url(it.get('poster_path'))
            pl['recent_items'] = items
            # Add item counts (movies/shows) for consistent stats display
            try:
                pl['item_counts'] = get_list_item_counts(pl['id'])
            except Exception:
                pl['item_counts'] = {'movies': 0, 'shows': 0}
        except Exception:
            pl['recent_items'] = []

    # For Reviews tab (all)
    all_reviews = get_user_recent_reviews(profile_user['id'], limit=None)
    for rr in all_reviews:
        rr['poster_url'] = tmdb.get_poster_url(rr.get('poster_path'))
        media_type = rr.get('media_type', 'movie')
        rr['go_url'] = f"/go/{media_type}/{rr.get('tmdb_id')}/"

    # Compute watched count for this user
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM user_watched WHERE user_id = %s", [profile_user['id']])
        watched_count = (cursor.fetchone() or [0])[0]

    # Followers/Following counts and whether current user follows this profile
    followers_count = 0
    following_count = 0
    followed_by_me = False
    with connection.cursor() as cursor:
        # If denormalized columns exist, prefer them; otherwise compute live
        try:
            cursor.execute("SELECT followers_count, following_count FROM users WHERE id = %s", [profile_user['id']])
            row = cursor.fetchone()
            if row and row[0] is not None and row[1] is not None:
                followers_count = row[0]
                following_count = row[1]
            else:
                raise Exception('No denormalized columns')
        except Exception:
            # Fallback to counts from user_follows
            cursor.execute("SELECT COUNT(*) FROM user_follows WHERE followee_id = %s", [profile_user['id']])
            followers_count = (cursor.fetchone() or [0])[0]
            cursor.execute("SELECT COUNT(*) FROM user_follows WHERE follower_id = %s", [profile_user['id']])
            following_count = (cursor.fetchone() or [0])[0]

        # Is current session user following this profile?
        current_uid = request.session.get('user_id')
        if current_uid and current_uid != profile_user['id']:
            cursor.execute("SELECT 1 FROM user_follows WHERE follower_id = %s AND followee_id = %s", [current_uid, profile_user['id']])
            followed_by_me = cursor.fetchone() is not None

    profile_stats = {
        'lists': lists_count,
        'watched': watched_count,
        'following': following_count,
        'followers': followers_count,
    }

    return render(request, 'profile.html', {
        'profile_user': profile_user,
        'is_own_profile': is_own_profile,
        'profile_settings': settings,
        'top_five': top_five,
        'recent_activity': recent_activity,
        'recent_reviews': recent_reviews,
        'all_lists': all_lists,
        'all_reviews': all_reviews,
    'profile_banner_url': profile_banner_url,
    'profile_stats': profile_stats,
    'followed_by_me': followed_by_me,
    })

@require_POST
def update_profile_settings(request):
    """Update profile settings for the current user (e.g., hide_fullname)."""
    uid = request.session.get('user_id')
    if not uid:
        return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)
    try:
        data = json.loads(request.body.decode('utf-8'))
        # Accept boolean-like values for hide_fullname and hide_follow_stats
        hide_fullname = data.get('hide_fullname')
        if isinstance(hide_fullname, str):
            hide_fullname = hide_fullname.lower() in ('1', 'true', 'yes', 'on')
        hide_follow_stats = data.get('hide_follow_stats')
        if isinstance(hide_follow_stats, str):
            hide_follow_stats = hide_follow_stats.lower() in ('1', 'true', 'yes', 'on')
        updates = {}
        if hide_fullname is not None:
            updates['hide_fullname'] = '1' if hide_fullname else '0'
        if hide_follow_stats is not None:
            updates['hide_follow_stats'] = '1' if hide_follow_stats else '0'
        if updates:
            set_user_settings(uid, updates)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@ensure_csrf_cookie
def movie_detail(request, slug):
    """Display detailed movie page"""
    tmdb = TMDBService()
    
    # Extract year from slug if present (e.g., "movie-name-2024")
    parts = slug.rsplit('-', 1)
    year = parts[1] if len(parts) == 2 and parts[1].isdigit() else None
    
    # Extract title from slug
    title_from_slug = parts[0].replace('-', ' ').title()
    
    # Search TMDB for the movie
    search_results = tmdb.search_movies(title_from_slug)
    
    movie = None
    if search_results and 'results' in search_results:
        # Try to find exact match by year if provided
        if year:
            for result in search_results['results']:
                release_year = result.get('release_date', '')[:4]
                if release_year == year:
                    movie = result
                    break
        
        # If no year match or no year provided, take first result
        if not movie and search_results['results']:
            movie = search_results['results'][0]
    
    if not movie:
        messages.error(request, 'Movie not found')
        return redirect('browse')
    
    # Get full movie details
    movie_id = movie['id']
    movie_details = tmdb.get_movie_details(movie_id)
    
    if movie_details:
        # Add poster and backdrop URLs
        movie_details['poster_url'] = tmdb.get_poster_url(movie_details.get('poster_path'))
        movie_details['backdrop_url'] = tmdb.get_backdrop_url(movie_details.get('backdrop_path'))
        
        # Get custom stats from our database
        custom_stats = get_content_stats(movie_id, 'movie')
        movie_details['custom_stats'] = custom_stats
        
        # Check if user has watched this movie
        has_watched = False
        if 'user_id' in request.session:
            has_watched = has_user_watched(request.session['user_id'], movie_id, 'movie')

        # Get reviews for this movie (include like metadata for current user)
        reviews = get_content_reviews(movie_id, 'movie', request.session.get('user_id'))

        # Generate proper slug for canonical URL
        release_year = movie_details.get('release_date', '')[:4]
        movie_details['slug'] = slugify_title(movie_details.get('title', ''), release_year)
    
    return render(request, 'movie_detail.html', {
        'movie': movie_details,
        'is_logged_in': 'user_id' in request.session,
        'has_watched': has_watched,
        'reviews': reviews
    })

@ensure_csrf_cookie
def tv_detail(request, slug):
    """Display detailed TV show page"""
    tmdb = TMDBService()
    
    # Extract year from slug if present
    parts = slug.rsplit('-', 1)
    year = parts[1] if len(parts) == 2 and parts[1].isdigit() else None
    
    # Extract title from slug
    title_from_slug = parts[0].replace('-', ' ').title()
    
    # Search TMDB for the TV show
    search_results = tmdb.search_tv(title_from_slug)
    
    show = None
    if search_results and 'results' in search_results:
        # Try to find exact match by year if provided
        if year:
            for result in search_results['results']:
                first_year = result.get('first_air_date', '')[:4]
                if first_year == year:
                    show = result
                    break
        
        # If no year match or no year provided, take first result
        if not show and search_results['results']:
            show = search_results['results'][0]
    
    if not show:
        messages.error(request, 'TV show not found')
        return redirect('browse')
    
    # Get full TV show details
    show_id = show['id']
    show_details = tmdb.get_tv_details(show_id)
    
    if show_details:
        # Add poster and backdrop URLs
        show_details['poster_url'] = tmdb.get_poster_url(show_details.get('poster_path'))
        show_details['backdrop_url'] = tmdb.get_backdrop_url(show_details.get('backdrop_path'))
        
        # Get custom stats from our database
        custom_stats = get_content_stats(show_id, 'tv')
        show_details['custom_stats'] = custom_stats
        
        # Check if user has watched this show
        has_watched = False
        if 'user_id' in request.session:
            has_watched = has_user_watched(request.session['user_id'], show_id, 'tv')

        # Get reviews for this show (include like metadata for current user)
        reviews = get_content_reviews(show_id, 'tv', request.session.get('user_id'))

        # Generate proper slug for canonical URL
        first_year = show_details.get('first_air_date', '')[:4]
        show_details['slug'] = slugify_title(show_details.get('name', ''), first_year)
    
    return render(request, 'tv_detail.html', {
        'show': show_details,
        'is_logged_in': 'user_id' in request.session,
        'has_watched': has_watched,
        'reviews': reviews
    })


def list_detail(request, username, listname):
    """Public list page by username/listname."""
    owner = cs_get_user_by_username(username)
    if not owner:
        return render(request, 'members.html', status=404)

    lst = get_list_by_user_and_name(owner['id'], listname)
    if not lst:
        return render(request, 'members.html', status=404)

    # If list is private, only owner can see it
    if not lst['is_public']:
        if request.session.get('user_id') != owner['id']:
            return render(request, 'members.html', status=403)

    items = get_list_items(lst['id'])
    user_id = request.session.get('user_id')
    watched_count = 0
    total_items = len(items)
    if user_id:
        for it in items:
            try:
                it['watched_by_me'] = has_user_watched(user_id, it.get('tmdb_id'), it.get('media_type'))
                it['reviewed_by_me'] = has_user_rated(user_id, it.get('tmdb_id'), it.get('media_type'))
                if it['watched_by_me']:
                    watched_count += 1
            except Exception:
                it['watched_by_me'] = False
                it['reviewed_by_me'] = False
    watched_percentage = 0
    if user_id and total_items > 0:
        watched_percentage = round((watched_count / total_items) * 100)
    comments = get_list_comments(lst['id'])

    # Used to mark like state
    liked_by_me = False
    if request.session.get('user_id'):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM list_likes WHERE user_id = %s AND list_id = %s", [request.session['user_id'], lst['id']])
            liked_by_me = cursor.fetchone() is not None

    is_list_owner = request.session.get('user_id') == owner['id']
    current_user_id = request.session.get('user_id')

    # Ensure owner.pfp is base64 for template (cs_get_user_by_username returns raw bytes)
    if owner and owner.get('pfp') is not None and not isinstance(owner['pfp'], str):
        try:
            owner['pfp'] = base64.b64encode(owner['pfp']).decode('utf-8')
        except Exception:
            owner['pfp'] = None

    return render(request, 'list_detail.html', {
        'list': lst,
        'owner': owner,
        'items': items,
        'comments': comments,
        'liked_by_me': liked_by_me,
        'is_logged_in': 'user_id' in request.session,
        'is_list_owner': is_list_owner,
        'current_user_id': current_user_id,
    'watched_percentage': watched_percentage,
    'watched_count': watched_count,
    'total_items': total_items,
    })


@require_POST
def toggle_follow(request):
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)
    try:
        payload = json.loads(request.body.decode('utf-8'))
        target_username = payload.get('username')
        if not target_username:
            return JsonResponse({'success': False, 'error': 'Missing username'}, status=400)

        # Resolve target user
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(%s)", [target_username])
            row = cursor.fetchone()
            if not row:
                return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
            target_id = row[0]

        user_id = request.session['user_id']
        if user_id == target_id:
            return JsonResponse({'success': False, 'error': 'Cannot follow yourself'}, status=400)

        followed = False
        with connection.cursor() as cursor:
            # Check if already following
            cursor.execute("SELECT id FROM user_follows WHERE follower_id = %s AND followee_id = %s", [user_id, target_id])
            row = cursor.fetchone()
            if row:
                # Unfollow
                cursor.execute("DELETE FROM user_follows WHERE id = %s", [row[0]])
                followed = False
                # If using denormalized counts, adjust optimistically
                try:
                    cursor.execute("UPDATE users SET followers_count = followers_count - 1 WHERE id = %s", [target_id])
                    cursor.execute("UPDATE users SET following_count = following_count - 1 WHERE id = %s", [user_id])
                except Exception:
                    pass
            else:
                # Follow
                cursor.execute("INSERT INTO user_follows (follower_id, followee_id) VALUES (%s, %s)", [user_id, target_id])
                followed = True
                try:
                    cursor.execute("UPDATE users SET followers_count = followers_count + 1 WHERE id = %s", [target_id])
                    cursor.execute("UPDATE users SET following_count = following_count + 1 WHERE id = %s", [user_id])
                except Exception:
                    pass

            # Return current follower count for target
            try:
                cursor.execute("SELECT followers_count FROM users WHERE id = %s", [target_id])
                followers_count = (cursor.fetchone() or [0])[0]
            except Exception:
                cursor.execute("SELECT COUNT(*) FROM user_follows WHERE followee_id = %s", [target_id])
                followers_count = (cursor.fetchone() or [0])[0]

        return JsonResponse({'success': True, 'followed': followed, 'followers': followers_count})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def delete_list_comment_view(request):
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)
    try:
        data = json.loads(request.body)
        comment_id = data.get('comment_id')
        if not comment_id:
            return JsonResponse({'success': False, 'error': 'Missing comment_id'}, status=400)
        result = delete_list_comment(request.session['user_id'], int(comment_id))
        return JsonResponse({'success': True, **result})
    except PermissionError as pe:
        return JsonResponse({'success': False, 'error': str(pe)}, status=403)
    except ValueError as ve:
        return JsonResponse({'success': False, 'error': str(ve)}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def toggle_like(request):
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)
    try:
        data = json.loads(request.body)
        list_id = data.get('list_id')
        if not list_id:
            return JsonResponse({'success': False, 'error': 'Missing list_id'}, status=400)
        result = toggle_like_list(request.session['user_id'], int(list_id))
        return JsonResponse({'success': True, **result})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def add_list_comment_view(request):
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)
    try:
        data = json.loads(request.body)
        list_id = data.get('list_id')
        text = data.get('comment_text', '')
        if not list_id:
            return JsonResponse({'success': False, 'error': 'Missing list_id'}, status=400)
        result = add_list_comment(request.session['user_id'], int(list_id), text)
        return JsonResponse({'success': True, 'comment': result})
    except ValueError as ve:
        return JsonResponse({'success': False, 'error': str(ve)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def toggle_review_like_view(request):
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)
    try:
        data = json.loads(request.body)
        rating_id = data.get('rating_id')
        if not rating_id:
            return JsonResponse({'success': False, 'error': 'Missing rating_id'}, status=400)
        result = toggle_like_review(request.session['user_id'], int(rating_id))
        return JsonResponse({'success': True, **result})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def mark_watched(request):
    """Mark content as watched for the current user"""
    # Check if user is logged in
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)
    
    try:
        data = json.loads(request.body)
        
        tmdb_id = data.get('tmdb_id')
        media_type = data.get('media_type')
        title = data.get('title')
        poster_path = data.get('poster_path')
        
        if not tmdb_id or not media_type or not title:
            return JsonResponse({'success': False, 'error': 'Missing required fields'}, status=400)
        
        user_id = request.session['user_id']
        
        # Mark as watched
        mark_as_watched(user_id, tmdb_id, media_type, title, poster_path)
        
        # Get updated stats
        stats = get_content_stats(tmdb_id, media_type)
        
        return JsonResponse({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def add_rating_view(request):
    """Add or update a user's rating for content"""
    # Check if user is logged in
    if 'user_id' not in request.session:
        return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)
    
    try:
        data = json.loads(request.body)
        
        tmdb_id = data.get('tmdb_id')
        media_type = data.get('media_type')
        title = data.get('title')
        score = data.get('score')
        review_text = data.get('review_text', '').strip() or None  # Convert empty string to None
        poster_path = data.get('poster_path')
        
        if not tmdb_id or not media_type or not title or score is None:
            return JsonResponse({'success': False, 'error': 'Missing required fields'}, status=400)
        
        # Validate score
        try:
            score = int(score)
            if score < 0 or score > 100:
                return JsonResponse({'success': False, 'error': 'Score must be between 0 and 100'}, status=400)
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Invalid score'}, status=400)
        
        user_id = request.session['user_id']
        
        # Add rating
        add_rating(user_id, tmdb_id, media_type, title, score, review_text, poster_path)
        
        # Get updated stats
        stats = get_content_stats(tmdb_id, media_type)
        
        return JsonResponse({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
