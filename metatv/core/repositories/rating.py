"""Repository for user content ratings (👍 like / 👎 dislike)"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from metatv.core.database import UserRatingDB


class RatingRepository:
    """CRUD for UserRatingDB — one rating per channel_id, upsert replaces."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, channel_id: str) -> Optional[int]:
        """Return +1, -1, or None if unrated."""
        row = self.session.get(UserRatingDB, channel_id)
        return row.rating if row else None

    def set(self, channel_id: str, rating: int) -> None:
        """Upsert a rating (+1 or -1)."""
        self.session.merge(
            UserRatingDB(channel_id=channel_id, rating=rating, rated_at=datetime.utcnow())
        )

    def clear(self, channel_id: str) -> None:
        """Remove rating if it exists."""
        row = self.session.get(UserRatingDB, channel_id)
        if row:
            self.session.delete(row)
