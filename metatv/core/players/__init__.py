"""Player plugin system for MetaTV"""

from metatv.core.players.base import PlayerPlugin
from metatv.core.players.mpv import MPVPlayer

__all__ = ["PlayerPlugin", "MPVPlayer"]
