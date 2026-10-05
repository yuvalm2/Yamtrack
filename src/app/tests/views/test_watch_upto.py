from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Episode,
    MediaTypes,
    Season,
    Sources,
    Status,
)

TOTAL_EPISODES = 6


class EpisodeWatchUptoViewTests(TestCase):
    """Test the episode_watch_upto endpoint."""

    def setUp(self):
        """Log in and stub the metadata providers."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.episodes_metadata = [
            {
                "episode_number": i,
                "image": f"img{i}.jpg",
                "still_path": None,
                "air_date": datetime(2023, 1, i, tzinfo=UTC),
            }
            for i in range(1, TOTAL_EPISODES + 1)
        ]

        def mock_metadata(
            media_type,
            _media_id,
            _source,
            season_numbers=None,
            **_kwargs,
        ):
            season_numbers = season_numbers or [1]
            if media_type == "tv_with_seasons":
                return {
                    f"season/{s}": {
                        "episodes": self.episodes_metadata,
                        "image": "season_img.jpg",
                    }
                    for s in season_numbers
                } | {
                    "title": "Friends",
                    "image": "tv_img.jpg",
                    "related": {
                        "seasons": [{"season_number": s} for s in season_numbers],
                    },
                }
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Friends",
                    "image": "tv_img.jpg",
                    "details": {"seasons": 1},
                }
            return {
                "title": "Friends",
                "episodes": self.episodes_metadata,
                "image": "season_img.jpg",
            }

        for target in (
            "app.views.services.get_media_metadata",
            "app.models.providers.services.get_media_metadata",
        ):
            patcher = patch(target)
            patcher.start().side_effect = mock_metadata
            self.addCleanup(patcher.stop)

    def post_watch_upto(self, episode_number):
        """Post the endpoint for the given episode."""
        return self.client.post(
            reverse("episode_watch_upto"),
            {
                "media_id": "1668",
                "season_number": 1,
                "episode_number": episode_number,
                "source": Sources.TMDB.value,
            },
        )

    def test_creates_the_season_and_the_episodes(self):
        """Posting for an untracked show creates the season and episodes 1-4."""
        response = self.post_watch_upto(4)

        self.assertEqual(response.status_code, 302)
        season = Season.objects.get(user=self.user, item__season_number=1)
        self.assertEqual(
            sorted(
                Episode.objects.filter(related_season=season).values_list(
                    "item__episode_number",
                    flat=True,
                ),
            ),
            [1, 2, 3, 4],
        )
        self.assertEqual(season.item.media_type, MediaTypes.SEASON.value)
        self.assertEqual(season.status, Status.IN_PROGRESS.value)

    def test_reports_how_many_episodes_were_marked(self):
        """The success message names the count and the target episode."""
        response = self.post_watch_upto(3)

        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertIn("Marked 3 episodes as watched, up to episode 3.", messages)

    def test_reports_when_there_was_nothing_to_do(self):
        """A repeat post adds nothing and says so."""
        self.post_watch_upto(3)
        response = self.post_watch_upto(3)

        self.assertEqual(Episode.objects.count(), 3)
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertIn(
            "Every released episode up to episode 3 was already watched.",
            messages,
        )
