"""
Service for managing content (movies/shows) in our database
"""
from django.db import connection
from datetime import datetime
import base64


def get_or_create_content(tmdb_id, media_type, title, poster_path=None, backdrop_path=None, release_date=None):
    """
    Get content by TMDB ID, or create it if it doesn't exist
    Returns: content_id
    """
    with connection.cursor() as cursor:
        # Try to get existing content
        cursor.execute("""
            SELECT id FROM content WHERE tmdb_id = %s AND media_type = %s
        """, [tmdb_id, media_type])
        
        row = cursor.fetchone()
        if row:
            return row[0]
        
        # Create new content
        cursor.execute("""
            INSERT INTO content (tmdb_id, media_type, title, poster_path, backdrop_path, release_date)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, [tmdb_id, media_type, title, poster_path, backdrop_path, release_date])
        
        return cursor.fetchone()[0]


def get_content_stats(tmdb_id, media_type):
    """
    Get custom stats for a piece of content
    Returns: dict with watched_count, list_count, avg_score
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT watched_count, list_count, avg_score
            FROM content
            WHERE tmdb_id = %s AND media_type = %s
        """, [tmdb_id, media_type])
        
        row = cursor.fetchone()
        if row:
            return {
                'watched_count': row[0],
                'list_count': row[1],
                'avg_score': float(row[2]) if row[2] else 0
            }
        return {'watched_count': 0, 'list_count': 0, 'avg_score': 0}


def mark_as_watched(user_id, tmdb_id, media_type, title, poster_path=None):
    """
    Mark content as watched by a user
    """
    with connection.cursor() as cursor:
        # Get or create content
        content_id = get_or_create_content(tmdb_id, media_type, title, poster_path)
        
        # Add to user_watched (ignore if already exists)
        cursor.execute("""
            INSERT INTO user_watched (user_id, content_id)
            VALUES (%s, %s)
            ON CONFLICT (user_id, content_id) DO NOTHING
        """, [user_id, content_id])
        
        # Update watched count
        cursor.execute("""
            UPDATE content
            SET watched_count = (SELECT COUNT(*) FROM user_watched WHERE content_id = %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, [content_id, content_id])


def add_rating(user_id, tmdb_id, media_type, title, score, review_text=None, poster_path=None):
    """
    Add or update a user's rating for content (0-100) with optional review text
    """
    with connection.cursor() as cursor:
        # Get or create content
        content_id = get_or_create_content(tmdb_id, media_type, title, poster_path)
        
        # Add or update rating
        cursor.execute("""
            INSERT INTO user_ratings (user_id, content_id, score, review_text)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, content_id) 
            DO UPDATE SET score = %s, review_text = %s, updated_at = CURRENT_TIMESTAMP
        """, [user_id, content_id, score, review_text, score, review_text])
        
        # Recalculate average score
        cursor.execute("""
            UPDATE content
            SET avg_score = (SELECT AVG(score) FROM user_ratings WHERE content_id = %s),
                total_scores = (SELECT COUNT(*) FROM user_ratings WHERE content_id = %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, [content_id, content_id, content_id])


def add_to_list(list_id, tmdb_id, media_type, title, poster_path=None):
    """
    Add content to a user's list
    """
    with connection.cursor() as cursor:
        # Get or create content
        content_id = get_or_create_content(tmdb_id, media_type, title, poster_path)
        
        # Add to list
        cursor.execute("""
            INSERT INTO list_items (list_id, content_id)
            VALUES (%s, %s)
            ON CONFLICT (list_id, content_id) DO NOTHING
        """, [list_id, content_id])
        
        # Update list count
        cursor.execute("""
            UPDATE content
            SET list_count = (SELECT COUNT(*) FROM list_items WHERE content_id = %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, [content_id, content_id])


def remove_from_list(list_id, tmdb_id, media_type):
    """
    Remove content from a user's list.
    Returns: dict with removed flag and updated list_count for the content.
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id FROM content WHERE tmdb_id = %s AND media_type = %s
        """, [tmdb_id, media_type])
        row = cursor.fetchone()
        if not row:
            return {'removed': False, 'list_count': 0}

        content_id = row[0]
        cursor.execute("""
            DELETE FROM list_items
            WHERE list_id = %s AND content_id = %s
        """, [list_id, content_id])

        removed = cursor.rowcount > 0
        cursor.execute("""
            UPDATE content
            SET list_count = (SELECT COUNT(*) FROM list_items WHERE content_id = %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, [content_id, content_id])

        cursor.execute("""
            SELECT list_count FROM content WHERE id = %s
        """, [content_id])
        count_row = cursor.fetchone()

        if removed:
            cursor.execute("""
                UPDATE user_lists
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, [list_id])

        return {
            'removed': removed,
            'list_count': (count_row[0] if count_row else 0) or 0,
        }


def get_user_lists(user_id, is_public: bool | None = None):
    """
    Return all lists for a user. If is_public is provided, filter by it.
    Each list: {id, name, description, is_public, created_at, updated_at}
    """
    with connection.cursor() as cursor:
        if is_public is None:
            cursor.execute(
                """
                SELECT id, name, description, is_public, likes_count, comments_count, created_at, updated_at
                FROM user_lists
                WHERE user_id = %s
                ORDER BY updated_at DESC, created_at DESC
                """,
                [user_id],
            )
        else:
            cursor.execute(
                """
                SELECT id, name, description, is_public, likes_count, comments_count, created_at, updated_at
                FROM user_lists
                WHERE user_id = %s AND is_public = %s
                ORDER BY updated_at DESC, created_at DESC
                """,
                [user_id, is_public],
            )

        rows = cursor.fetchall() or []
        lists = []
        for row in rows:
            lists.append(
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "is_public": bool(row[3]),
                    "likes_count": row[4] or 0,
                    "comments_count": row[5] or 0,
                    "created_at": row[6],
                    "updated_at": row[7],
                }
            )
        return lists


def user_has_list_name(user_id, name: str) -> bool:
    """Case-insensitive uniqueness check for list name per user."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM user_lists
            WHERE user_id = %s AND LOWER(name) = LOWER(%s)
            """,
            [user_id, name],
        )
        return cursor.fetchone() is not None


def create_user_list(user_id, name: str, description: str | None, is_public: bool):
    """
    Create a list for a user, enforcing per-user unique name (case-insensitive).
    Returns: dict with the created list {id, name, description, is_public}
    """
    if not name or not name.strip():
        raise ValueError("List name is required")

    name = name.strip()
    if len(name) > 200:
        raise ValueError("List name must be 200 characters or fewer")

    if user_has_list_name(user_id, name):
        raise ValueError("You already have a list with that name")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_lists (user_id, name, description, is_public)
            VALUES (%s, %s, %s, %s)
            RETURNING id, name, description, is_public, created_at, updated_at
            """,
            [user_id, name, description, is_public],
        )
        row = cursor.fetchone()
        return {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "is_public": bool(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
        }


def verify_user_owns_list(user_id, list_id) -> bool:
    """Ensure the list belongs to the given user."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM user_lists
            WHERE id = %s AND user_id = %s
            """,
            [list_id, user_id],
        )
        return cursor.fetchone() is not None


def get_user_by_username(username: str):
    """Return user row dict by username (case-insensitive) or None."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, username, firstname, lastname, email, pfp
            FROM users WHERE LOWER(username) = LOWER(%s)
            """,
            [username],
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            'id': row[0], 'username': row[1], 'firstname': row[2],
            'lastname': row[3], 'email': row[4], 'pfp': row[5]
        }


def get_list_by_user_and_name(user_id: int, name_or_slug: str):
    """
    Fetch a list by user and a provided name/slug (case-insensitive, hyphens->spaces).
    Returns: dict or None
    """
    # Convert slug-like to name guess (replace dashes with spaces)
    guess_name = name_or_slug.replace('-', ' ')
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, user_id, name, description, is_public,
                   likes_count, comments_count, created_at, updated_at
            FROM user_lists
            WHERE user_id = %s AND LOWER(name) = LOWER(%s)
            """,
            [user_id, guess_name],
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            'id': row[0], 'user_id': row[1], 'name': row[2], 'description': row[3],
            'is_public': bool(row[4]), 'likes_count': row[5] or 0, 'comments_count': row[6] or 0,
            'created_at': row[7], 'updated_at': row[8]
        }


def get_list_items(list_id: int):
    """Return items for a list with content info suitable for rendering."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.tmdb_id, c.media_type, c.title, c.poster_path
            FROM list_items li
            JOIN content c ON li.content_id = c.id
            WHERE li.list_id = %s
            ORDER BY li.added_at DESC
            """,
            [list_id],
        )
        rows = cursor.fetchall() or []
        items = []
        for r in rows:
            items.append({
                'tmdb_id': r[0],
                'media_type': r[1],
                'title': r[2],
                'poster_path': r[3],
            })
        return items


def get_recent_list_items(list_id: int, limit: int = 5):
    """Return most recent items (with poster) for a list (limit default 5)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.tmdb_id, c.media_type, c.title, c.poster_path
            FROM list_items li
            JOIN content c ON li.content_id = c.id
            WHERE li.list_id = %s
            ORDER BY li.added_at DESC
            LIMIT %s
            """,
            [list_id, limit],
        )
        rows = cursor.fetchall() or []
        return [
            {
                'tmdb_id': r[0],
                'media_type': r[1],
                'title': r[2],
                'poster_path': r[3],
            }
            for r in rows
        ]


def get_popular_lists(limit: int = 12):
    """Return top public lists ordered by likes_count desc, then updated_at desc.
    Includes creator basic info.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ul.id, ul.user_id, ul.name, ul.description, ul.likes_count, ul.comments_count,
                   ul.created_at, ul.updated_at,
                   u.username, u.pfp
            FROM user_lists ul
            JOIN users u ON ul.user_id = u.id
            WHERE ul.is_public = TRUE
            ORDER BY ul.likes_count DESC NULLS LAST, ul.updated_at DESC
            LIMIT %s
            """,
            [limit],
        )
        rows = cursor.fetchall() or []
        popular = []
        for r in rows:
            popular.append({
                'id': r[0],
                'user_id': r[1],
                'name': r[2],
                'description': r[3],
                'likes_count': r[4] or 0,
                'comments_count': r[5] or 0,
                'created_at': r[6],
                'updated_at': r[7],
                'username': r[8],
                'pfp': base64.b64encode(r[9]).decode('utf-8') if r[9] else None,
            })
        return popular


def get_top_lists_by_engagement(limit: int = 6):
    """Return public lists ranked by engagement = likes_count + comments_count (desc).
    Includes creator info (username, pfp).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ul.id, ul.user_id, ul.name, ul.description,
                   COALESCE(ul.likes_count,0) AS likes_count,
                   COALESCE(ul.comments_count,0) AS comments_count,
                   ul.created_at, ul.updated_at,
                   u.username, u.pfp,
                   (COALESCE(ul.likes_count,0) + COALESCE(ul.comments_count,0)) AS engagement_score
            FROM user_lists ul
            JOIN users u ON ul.user_id = u.id
            WHERE ul.is_public = TRUE
            ORDER BY engagement_score DESC, ul.likes_count DESC NULLS LAST, ul.updated_at DESC
            LIMIT %s
            """,
            [limit],
        )
        rows = cursor.fetchall() or []
        out = []
        for r in rows:
            out.append({
                'id': r[0],
                'user_id': r[1],
                'name': r[2],
                'description': r[3],
                'likes_count': r[4] or 0,
                'comments_count': r[5] or 0,
                'created_at': r[6],
                'updated_at': r[7],
                'username': r[8],
                'pfp': base64.b64encode(r[9]).decode('utf-8') if r[9] else None,
                'engagement_score': (r[10] or 0),
            })
        return out


def get_list_item_counts(list_id: int):
    """Return total items and split by media type for a list."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 
                COUNT(*) AS total,
                SUM(CASE WHEN c.media_type = 'movie' THEN 1 ELSE 0 END) AS movies,
                SUM(CASE WHEN c.media_type = 'tv' THEN 1 ELSE 0 END) AS shows
            FROM list_items li
            JOIN content c ON li.content_id = c.id
            WHERE li.list_id = %s
            """,
            [list_id],
        )
        row = cursor.fetchone() or (0, 0, 0)
        return {
            'total': row[0] or 0,
            'movies': row[1] or 0,
            'shows': row[2] or 0,
        }


def get_user_top_rated_content(user_id: int, limit: int = 5):
    """Return user's top-rated movies/shows with content display fields."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.tmdb_id, c.media_type, c.title, c.poster_path, ur.score
            FROM user_ratings ur
            JOIN content c ON ur.content_id = c.id
            WHERE ur.user_id = %s AND ur.score IS NOT NULL
            ORDER BY ur.score DESC, ur.updated_at DESC
            LIMIT %s
            """,
            [user_id, limit],
        )
        rows = cursor.fetchall() or []
        return [
            {
                'tmdb_id': r[0], 'media_type': r[1], 'title': r[2], 'poster_path': r[3], 'score': float(r[4]) if r[4] is not None else None
            } for r in rows
        ]


def get_user_recent_reviews(user_id: int, limit: int | None = 5):
    """Return user's recent reviews with content fields and like counts."""
    with connection.cursor() as cursor:
        sql = (
            """
            SELECT ur.id AS rating_id, ur.score, ur.review_text, ur.updated_at, COALESCE(ur.likes_count,0) AS likes_count,
                   c.tmdb_id, c.media_type, c.title, c.poster_path
            FROM user_ratings ur
            JOIN content c ON ur.content_id = c.id
            WHERE ur.user_id = %s AND ur.review_text IS NOT NULL
            ORDER BY ur.updated_at DESC
            """
        )
        if limit is not None:
            sql += " LIMIT %s"
            params = [user_id, limit]
        else:
            params = [user_id]
        cursor.execute(sql, params)
        rows = cursor.fetchall() or []
        return [
            {
                'rating_id': row[0],
                'score': float(row[1]) if row[1] is not None else None,
                'review_text': row[2],
                'updated_at': row[3],
                'likes_count': row[4],
                'tmdb_id': row[5],
                'media_type': row[6],
                'title': row[7],
                'poster_path': row[8],
            }
            for row in rows
        ]


def get_user_recent_activity(user_id: int, limit: int = 5):
    """Return mixed recent activity: watched and items added to any of the user's lists."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT action, ts, ord, tmdb_id, media_type, title, poster_path FROM (
              SELECT 'watched' AS action,
                     uw.watched_at AS ts,
                     uw.id AS ord,
                     c.tmdb_id, c.media_type, c.title, c.poster_path
              FROM user_watched uw
              JOIN content c ON uw.content_id = c.id
              WHERE uw.user_id = %s
              UNION ALL
              SELECT 'listed' AS action,
                     li.added_at AS ts,
                     li.id AS ord,
                     c.tmdb_id, c.media_type, c.title, c.poster_path
              FROM list_items li
              JOIN user_lists ul ON li.list_id = ul.id AND ul.user_id = %s
              JOIN content c ON li.content_id = c.id
            ) ev
            ORDER BY COALESCE(ts, to_timestamp(0)) DESC, ord DESC
            LIMIT %s
            """,
            [user_id, user_id, limit],
        )
        rows = cursor.fetchall() or []
        return [
            {
                'action': r[0], 'timestamp': r[1], 'tmdb_id': r[3], 'media_type': r[4], 'title': r[5], 'poster_path': r[6]
            } for r in rows
        ]


def search_lists(query: str, viewer_user_id: int | None = None, limit: int = 24, offset: int = 0):
    """Search lists by name/description/username. Returns public lists, plus viewer's own private.
    Fields: id, user_id, name, description, is_public, likes_count, comments_count, updated_at, username, pfp
    """
    q = f"%{query.strip()}%"
    with connection.cursor() as cursor:
        if viewer_user_id:
            cursor.execute(
                """
                SELECT ul.id, ul.user_id, ul.name, ul.description, ul.is_public,
                       ul.likes_count, ul.comments_count, ul.updated_at,
                       u.username, u.pfp
                FROM user_lists ul
                JOIN users u ON u.id = ul.user_id
                WHERE (
                    ul.is_public = TRUE OR ul.user_id = %s
                )
                AND (
                    ul.name ILIKE %s OR ul.description ILIKE %s OR u.username ILIKE %s
                )
                ORDER BY ul.likes_count DESC NULLS LAST, ul.updated_at DESC
                LIMIT %s OFFSET %s
                """,
                [viewer_user_id, q, q, q, limit, offset],
            )
        else:
            cursor.execute(
                """
                SELECT ul.id, ul.user_id, ul.name, ul.description, ul.is_public,
                       ul.likes_count, ul.comments_count, ul.updated_at,
                       u.username, u.pfp
                FROM user_lists ul
                JOIN users u ON u.id = ul.user_id
                WHERE ul.is_public = TRUE AND (
                    ul.name ILIKE %s OR ul.description ILIKE %s OR u.username ILIKE %s
                )
                ORDER BY ul.likes_count DESC NULLS LAST, ul.updated_at DESC
                LIMIT %s OFFSET %s
                """,
                [q, q, q, limit, offset],
            )
        rows = cursor.fetchall() or []
        return [
            {
                'id': r[0], 'user_id': r[1], 'name': r[2], 'description': r[3], 'is_public': bool(r[4]),
                'likes_count': r[5] or 0, 'comments_count': r[6] or 0, 'updated_at': r[7],
                'username': r[8], 'pfp': base64.b64encode(r[9]).decode('utf-8') if r[9] else None,
            }
            for r in rows
        ]


def user_liked_list(user_id: int, list_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM list_likes WHERE user_id = %s AND list_id = %s",
            [user_id, list_id],
        )
        return cursor.fetchone() is not None


def toggle_like_list(user_id: int, list_id: int):
    """Toggle like. Returns dict: {liked: bool, likes_count: int}"""
    with connection.cursor() as cursor:
        # Check current state
        cursor.execute(
            "SELECT 1 FROM list_likes WHERE user_id = %s AND list_id = %s",
            [user_id, list_id],
        )
        exists = cursor.fetchone() is not None

        if exists:
            cursor.execute(
                "DELETE FROM list_likes WHERE user_id = %s AND list_id = %s",
                [user_id, list_id],
            )
            liked_now = False
        else:
            cursor.execute(
                "INSERT INTO list_likes (user_id, list_id) VALUES (%s, %s)",
                [user_id, list_id],
            )
            liked_now = True

        # Update count
        cursor.execute(
            """
            UPDATE user_lists
            SET likes_count = (SELECT COUNT(*) FROM list_likes WHERE list_id = %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING likes_count
            """,
            [list_id, list_id],
        )
        likes_count = cursor.fetchone()[0]
        return { 'liked': liked_now, 'likes_count': likes_count }


def add_list_comment(user_id: int, list_id: int, comment_text: str):
    if not comment_text or not comment_text.strip():
        raise ValueError("Comment cannot be empty")
    text = comment_text.strip()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO list_comments (list_id, user_id, comment_text)
            VALUES (%s, %s, %s)
            RETURNING id, created_at, updated_at
            """,
            [list_id, user_id, text],
        )
        row = cursor.fetchone()
        # Update count
        cursor.execute(
            """
            UPDATE user_lists
            SET comments_count = (SELECT COUNT(*) FROM list_comments WHERE list_id = %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING comments_count
            """,
            [list_id, list_id],
        )
        comments_count = cursor.fetchone()[0]
        return {
            'id': row[0],
            'comment_text': text,
            'created_at': row[1],
            'updated_at': row[2],
            'comments_count': comments_count,
        }


def get_list_comments(list_id: int):
    """Return comments with user display info for a list."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT lc.id, lc.comment_text, lc.created_at, lc.updated_at,
                   u.id as user_id, u.username, u.pfp
            FROM list_comments lc
            JOIN users u ON lc.user_id = u.id
            WHERE lc.list_id = %s
            ORDER BY lc.created_at DESC
            """,
            [list_id],
        )
        comments = []
        for row in cursor.fetchall() or []:
            comments.append({
                'id': row[0],
                'comment_text': row[1],
                'created_at': row[2],
                'updated_at': row[3],
                'user_id': row[4],
                'username': row[5],
                'pfp': base64.b64encode(row[6]).decode('utf-8') if row[6] else None,
            })
        return comments


def delete_list_comment(actor_user_id: int, comment_id: int):
    """Delete a list comment if permitted.
    Allowed if actor is the comment author OR the owner of the list the comment belongs to.
    Returns updated comments_count for that list.
    """
    with connection.cursor() as cursor:
        # Find the comment and its list/author
        cursor.execute(
            """
            SELECT lc.list_id, lc.user_id
            FROM list_comments lc
            WHERE lc.id = %s
            """,
            [comment_id],
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("Comment not found")
        list_id, comment_user_id = row[0], row[1]

        # Find owner of the list
        cursor.execute("SELECT user_id FROM user_lists WHERE id = %s", [list_id])
        list_row = cursor.fetchone()
        if not list_row:
            raise ValueError("List not found")
        list_owner_id = list_row[0]

        # Permission check
        if actor_user_id != comment_user_id and actor_user_id != list_owner_id:
            raise PermissionError("Not allowed to delete this comment")

        # Perform delete
        cursor.execute("DELETE FROM list_comments WHERE id = %s", [comment_id])

        # Update count on the list
        cursor.execute(
            """
            UPDATE user_lists
            SET comments_count = (SELECT COUNT(*) FROM list_comments WHERE list_id = %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING comments_count
            """,
            [list_id, list_id],
        )
        updated_count = cursor.fetchone()[0]

        return {
            'deleted': True,
            'comments_count': updated_count,
            'list_id': list_id,
        }


def enrich_content_with_stats(content_list):
    """
    Add custom stats to a list of content from TMDB API
    content_list: list of dicts with tmdb_id and media_type
    """
    if not content_list:
        return content_list
    
    # Build a map of (tmdb_id, media_type) -> stats
    stats_map = {}
    with connection.cursor() as cursor:
        for item in content_list:
            tmdb_id = item.get('id')
            media_type = item.get('media_type', 'movie')
            
            cursor.execute("""
                SELECT watched_count, list_count, avg_score
                FROM content
                WHERE tmdb_id = %s AND media_type = %s
            """, [tmdb_id, media_type])
            
            row = cursor.fetchone()
            if row:
                stats_map[(tmdb_id, media_type)] = {
                    'watched_count': row[0],
                    'list_count': row[1],
                    'avg_score': float(row[2]) if row[2] else 0
                }
    
    # Add stats to each item
    for item in content_list:
        tmdb_id = item.get('id')
        media_type = item.get('media_type', 'movie')
        key = (tmdb_id, media_type)
        
        if key in stats_map:
            item['custom_stats'] = stats_map[key]
        else:
            item['custom_stats'] = {'watched_count': 0, 'list_count': 0, 'avg_score': 0}
    
    return content_list


def has_user_watched(user_id, tmdb_id, media_type):
    """
    Check if a user has watched a specific piece of content
    Returns: Boolean
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 1 
            FROM user_watched uw
            JOIN content c ON uw.content_id = c.id
            WHERE uw.user_id = %s AND c.tmdb_id = %s AND c.media_type = %s
        """, [user_id, tmdb_id, media_type])
        
        return cursor.fetchone() is not None


def has_user_rated(user_id, tmdb_id, media_type):
    """
    Check if a user has submitted a rating or review for a specific piece of content
    Returns: Boolean
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 1 
            FROM user_ratings ur
            JOIN content c ON ur.content_id = c.id
            WHERE ur.user_id = %s AND c.tmdb_id = %s AND c.media_type = %s
        """, [user_id, tmdb_id, media_type])
        return cursor.fetchone() is not None


def get_content_reviews(tmdb_id, media_type, current_user_id=None):
    """
    Get all reviews for a specific piece of content
    Returns: List of review dictionaries with user info
    Includes per-review like metadata (likes_count, liked_by_me) and rating_id.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 
                u.id as user_id,
                u.username,
                u.pfp,
                ur.id as rating_id,
                ur.score,
                ur.review_text,
                ur.rated_at,
                ur.updated_at,
                COALESCE(ur.likes_count, 0) AS likes_count,
                CASE 
                    WHEN %s IS NULL THEN FALSE
                    ELSE EXISTS (
                        SELECT 1 FROM user_rating_likes url
                        WHERE url.rating_id = ur.id AND url.user_id = %s
                    )
                END AS liked_by_me
            FROM user_ratings ur
            JOIN content c ON ur.content_id = c.id
            JOIN users u ON ur.user_id = u.id
            WHERE c.tmdb_id = %s AND c.media_type = %s AND ur.review_text IS NOT NULL
            ORDER BY ur.updated_at DESC
            """,
            [current_user_id, current_user_id, tmdb_id, media_type],
        )

        columns = [col[0] for col in cursor.description]
        reviews = []
        for row in cursor.fetchall():
            review = dict(zip(columns, row))
            # Convert pfp bytes to base64 if it exists
            if review.get('pfp'):
                review['pfp'] = base64.b64encode(review['pfp']).decode('utf-8')
            reviews.append(review)

        return reviews


def toggle_like_review(user_id: int, rating_id: int):
    """Toggle like on a user rating (review).
    Returns dict: { liked: bool, likes_count: int }
    """
    with connection.cursor() as cursor:
        # Check if like exists
        cursor.execute(
            "SELECT 1 FROM user_rating_likes WHERE user_id = %s AND rating_id = %s",
            [user_id, rating_id],
        )
        exists = cursor.fetchone() is not None

        if exists:
            cursor.execute(
                "DELETE FROM user_rating_likes WHERE user_id = %s AND rating_id = %s",
                [user_id, rating_id],
            )
            liked_now = False
        else:
            cursor.execute(
                "INSERT INTO user_rating_likes (user_id, rating_id) VALUES (%s, %s)",
                [user_id, rating_id],
            )
            liked_now = True

        # Update cached likes_count on the rating without touching updated_at
        cursor.execute(
            """
            UPDATE user_ratings
            SET likes_count = (SELECT COUNT(*) FROM user_rating_likes WHERE rating_id = %s)
            WHERE id = %s
            RETURNING COALESCE(likes_count, 0)
            """,
            [rating_id, rating_id],
        )
        likes_count = cursor.fetchone()[0]
        return { 'liked': liked_now, 'likes_count': likes_count }


def get_popular_reviews(limit: int = 8, current_user_id: int | None = None):
    """Return most popular reviews (by likes_count desc, then recent update).
    Includes user info, content info, and liked_by_me for current user.
    Only returns rows where review_text IS NOT NULL.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 
                ur.id AS rating_id,
                ur.score,
                ur.review_text,
                ur.updated_at,
                COALESCE(ur.likes_count, 0) AS likes_count,
                u.id AS user_id,
                u.username,
                u.pfp,
                c.tmdb_id,
                c.media_type,
                c.title,
                c.poster_path,
                CASE
                    WHEN %s IS NULL THEN FALSE
                    ELSE EXISTS (
                        SELECT 1 FROM user_rating_likes url
                        WHERE url.rating_id = ur.id AND url.user_id = %s
                    )
                END AS liked_by_me
            FROM user_ratings ur
            JOIN content c ON ur.content_id = c.id
            JOIN users u ON ur.user_id = u.id
            WHERE ur.review_text IS NOT NULL
            ORDER BY COALESCE(ur.likes_count, 0) DESC, ur.updated_at DESC
            LIMIT %s
            """,
            [current_user_id, current_user_id, limit],
        )
        cols = [c[0] for c in cursor.description]
        out = []
        for row in cursor.fetchall() or []:
            rec = dict(zip(cols, row))
            if rec.get('pfp'):
                rec['pfp'] = base64.b64encode(rec['pfp']).decode('utf-8')
            out.append(rec)
        return out


def get_recently_reviewed_content(limit=6):
    """
    Get the most recently reviewed content (movies and TV shows)
    Returns: List of content with their latest review info and stats
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                c.tmdb_id,
                c.media_type,
                c.title,
                c.poster_path,
                c.watched_count,
                c.list_count,
                c.avg_score,
                MAX(ur.updated_at) as latest_review_date
            FROM content c
            JOIN user_ratings ur ON c.id = ur.content_id
            WHERE ur.review_text IS NOT NULL
            GROUP BY c.tmdb_id, c.media_type, c.title, c.poster_path, c.watched_count, c.list_count, c.avg_score
            ORDER BY latest_review_date DESC
            LIMIT %s
        """, [limit])
        
        content_list = []
        for row in cursor.fetchall():
            content = {
                'tmdb_id': row[0],
                'media_type': row[1],
                'title': row[2],
                'poster_path': row[3],
                'custom_stats': {
                    'watched_count': row[4],
                    'list_count': row[5],
                    'avg_score': float(row[6]) if row[6] else 0
                }
            }
            content_list.append(content)
        
        return content_list
