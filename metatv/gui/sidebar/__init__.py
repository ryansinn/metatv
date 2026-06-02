"""metatv.gui.sidebar — collapsible sidebar section widgets."""

from metatv.gui.sidebar.base import CollapsibleSection
from metatv.gui.sidebar.sources import ProviderItemWidget, SourcesSection
from metatv.gui.sidebar.alerts import WatchAlertsSection
from metatv.gui.sidebar.history import HistoryItemWidget, HistorySection
from metatv.gui.sidebar.favorites import FavoritesSection
from metatv.gui.sidebar.recommended import RecommendedSection
from metatv.gui.sidebar.queue import WatchQueueSection

__all__ = [
    "CollapsibleSection",
    "ProviderItemWidget",
    "HistoryItemWidget",
    "SourcesSection",
    "WatchAlertsSection",
    "HistorySection",
    "FavoritesSection",
    "RecommendedSection",
    "WatchQueueSection",
]
