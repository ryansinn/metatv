"""Repository pattern for data access layer - cleanly separates business logic from database queries"""

from sqlalchemy.orm import Session

from .provider import ProviderRepository
from .channel import ChannelRepository
from .episode import EpisodeRepository
from .season import SeasonRepository
from .filter import FilterRepository
from .alert import AlertRepository
from .rating import RatingRepository
from .queue import WatchQueueRepository
from .epg import EpgRepository
from .analytics import AnalyticsRepository
from .tag import TagRepository


class RepositoryFactory:
    """Factory for creating repository instances with a shared session"""

    def __init__(self, session: Session):
        self.session = session
        self._providers = None
        self._channels = None
        self._episodes = None
        self._seasons = None
        self._filters = None
        self._alerts = None
        self._ratings = None
        self._queue = None
        self._epg = None
        self._analytics = None
        self._tags = None
    
    @property
    def providers(self) -> ProviderRepository:
        """Get provider repository"""
        if self._providers is None:
            self._providers = ProviderRepository(self.session)
        return self._providers
    
    @property
    def channels(self) -> ChannelRepository:
        """Get channel repository"""
        if self._channels is None:
            self._channels = ChannelRepository(self.session)
        return self._channels
    
    @property
    def episodes(self) -> EpisodeRepository:
        """Get episode repository"""
        if self._episodes is None:
            self._episodes = EpisodeRepository(self.session)
        return self._episodes
    
    @property
    def seasons(self) -> SeasonRepository:
        """Get season repository"""
        if self._seasons is None:
            self._seasons = SeasonRepository(self.session)
        return self._seasons
    
    @property
    def filters(self) -> FilterRepository:
        """Get filter repository"""
        if self._filters is None:
            self._filters = FilterRepository(self.session)
        return self._filters
    
    @property
    def alerts(self) -> AlertRepository:
        """Get alert repository"""
        if self._alerts is None:
            self._alerts = AlertRepository(self.session)
        return self._alerts

    @property
    def ratings(self) -> RatingRepository:
        """Get rating repository"""
        if self._ratings is None:
            self._ratings = RatingRepository(self.session)
        return self._ratings

    @property
    def queue(self) -> WatchQueueRepository:
        """Get watch queue repository"""
        if self._queue is None:
            self._queue = WatchQueueRepository(self.session)
        return self._queue

    @property
    def epg(self) -> EpgRepository:
        """Get EPG repository"""
        if self._epg is None:
            self._epg = EpgRepository(self.session)
        return self._epg

    @property
    def analytics(self) -> AnalyticsRepository:
        """Get analytics repository"""
        if self._analytics is None:
            self._analytics = AnalyticsRepository(self.session)
        return self._analytics

    @property
    def tags(self) -> TagRepository:
        """Get tag repository"""
        if self._tags is None:
            self._tags = TagRepository(self.session)
        return self._tags


# Export all repositories and factory for convenience
__all__ = [
    'RepositoryFactory',
    'ProviderRepository',
    'ChannelRepository',
    'EpisodeRepository',
    'SeasonRepository',
    'FilterRepository',
    'AlertRepository',
    'RatingRepository',
    'WatchQueueRepository',
    'EpgRepository',
    'AnalyticsRepository',
    'TagRepository',
]
