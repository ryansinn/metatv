"""Turkish "N. Bölüm" episodes filed as movies collapse into their show (ledger F32).

4,634 movie rows on the owner's library were 305 Turkish shows, one row per
episode ("Kızılcık Şerbeti 136. Bölüm @showtv"). With the episode lifted out,
``detected_title`` is the show and ``content_key`` collapses them, as SxxExx
episodes already were.
"""

from __future__ import annotations

import pytest

from metatv.core.channel_name_utils import parse_channel_name


@pytest.mark.parametrize("name, show, episode", [
    ("Yeraltı 14. Bölüm", "Yeraltı", "14"),
    ("Taşacak Bu Deniz 27. Bölüm @trt1", "Taşacak Bu Deniz", "27"),
    ("Arka Sokaklar 748. Bölüm _ Full Bölüm", "Arka Sokaklar", "748"),
    ("Kuruluş Osman 94.Bolum (FİNAL)", "Kuruluş Osman", "94"),
])
def test_the_episode_comes_out_and_the_show_stays(name, show, episode):
    parsed = parse_channel_name(name)
    assert (parsed.bare_name, parsed.episode) == (show, episode)


def test_a_bare_episode_label_is_left_alone():
    assert parse_channel_name("12. Bölüm").bare_name == "12. Bölüm"


def test_two_episodes_of_one_show_share_a_content_key():
    from types import SimpleNamespace

    from metatv.core.content_identity import content_key_for

    def row(name):
        p = parse_channel_name(name)
        return SimpleNamespace(media_type="movie", detected_title=p.bare_name, detected_year=None,
                               detected_tmdb_id=None, name=name, raw_data=None)
    assert content_key_for(row("Yeraltı 14. Bölüm")) == content_key_for(row("Yeraltı 15. Bölüm @trt1"))


def test_an_absolute_bolum_after_sxxexx_goes_too():
    """14 Konusanlar rows kept "76 Bolum" in the title after the first pass."""
    parsed = parse_channel_name("Konusanlar S02E04 76. Bolum - 1080p EXXEN Web-DL AAC H.264 - TURG")
    assert (parsed.bare_name, parsed.season, parsed.episode) == ("Konusanlar", "02", "04")
