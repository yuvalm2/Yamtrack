from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)

TOTAL_EPISODES = 10


class SeasonWatchUpto(TestCase):
    """Test Season.watch_upto and the status reconciliation it triggers."""

    def setUp(self):
        """Create a season of 10 aired episodes with the first two watched."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.episodes_metadata = [
            {
                "episode_number": i,
                "image": f"img{i}.jpg",
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
                    f"season/{s}": {"episodes": self.episodes_metadata}
                    for s in season_numbers
                } | {
                    "related": {
                        "seasons": [{"season_number": s} for s in season_numbers],
                    },
                }
            return {"episodes": self.episodes_metadata, "image": "season_img.jpg"}

        self.metadata_patcher = patch(
            "app.models.providers.services.get_media_metadata",
        )
        self.mock_get_metadata = self.metadata_patcher.start()
        self.mock_get_metadata.side_effect = mock_metadata
        self.addCleanup(self.metadata_patcher.stop)

        tv_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Friends",
            image="http://example.com/image.jpg",
        )
        self.tv = TV(item=tv_item, user=self.user, status=Status.IN_PROGRESS.value)
        TV.save_base(self.tv)

        season_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )

        for episode_number in (1, 2):
            self.watch_without_cascade(episode_number)

    def watch_without_cascade(self, episode_number, end_date=None):
        """Add a watched episode without running Episode.save()'s cascades."""
        item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=episode_number,
        )
        episode = Episode(
            item=item,
            related_season=self.season,
            end_date=end_date or datetime(2023, 6, episode_number, tzinfo=UTC),
        )
        Episode.save_base(episode)
        return episode

    def watched_episode_numbers(self):
        """Return the watched episode numbers, including duplicates."""
        return sorted(
            Episode.objects.filter(related_season=self.season).values_list(
                "item__episode_number",
                flat=True,
            ),
        )

    def test_fills_the_gap_up_to_the_chosen_episode(self):
        """Only the missing episodes at or below the target are created."""
        created = self.season.watch_upto(5)

        self.assertEqual(created, 3)
        self.assertEqual(self.watched_episode_numbers(), [1, 2, 3, 4, 5])

    def test_leaves_already_watched_episodes_alone(self):
        """A second call adds nothing, so no episode gains a repeat."""
        self.season.watch_upto(5)
        created = self.season.watch_upto(5)

        self.assertEqual(created, 0)
        self.assertEqual(self.watched_episode_numbers(), [1, 2, 3, 4, 5])

    def test_backfills_below_an_already_watched_episode(self):
        """Watching out of order then backfilling adds no repeat to episode 7."""
        self.watch_without_cascade(7)

        created = self.season.watch_upto(7)

        self.assertEqual(created, 4)
        self.assertEqual(self.watched_episode_numbers(), [1, 2, 3, 4, 5, 6, 7])

    def test_skips_unreleased_episodes(self):
        """An episode that has not aired yet is not marked watched."""
        unaired = timezone.now() + timedelta(days=30)
        self.episodes_metadata[4]["air_date"] = unaired

        created = self.season.watch_upto(6)

        self.assertEqual(created, 3)
        self.assertEqual(self.watched_episode_numbers(), [1, 2, 3, 4, 6])

    def test_completes_the_season_at_the_finale(self):
        """Reaching the last episode completes the season and the show."""
        self.season.watch_upto(TOTAL_EPISODES)

        self.season.refresh_from_db()
        self.tv.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)
        self.assertEqual(self.tv.status, Status.COMPLETED.value)

    def test_leaves_a_part_watched_season_in_progress(self):
        """Stopping short of the finale must not complete the season.

        get_completion_status() would report COMPLETED here, because every
        remaining episode has already aired -- which is why watch_upto does not
        use it.
        """
        self.season.watch_upto(5)

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_keeps_a_completed_season_completed_when_backfilling(self):
        """Backfilling a gap below a watched finale must not reopen the season."""
        self.watch_without_cascade(TOTAL_EPISODES)
        Season.objects.filter(pk=self.season.pk).update(
            status=Status.COMPLETED.value,
        )
        self.season.refresh_from_db()

        created = self.season.watch_upto(TOTAL_EPISODES)

        self.season.refresh_from_db()
        self.assertEqual(created, TOTAL_EPISODES - 3)
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_returns_zero_when_nothing_is_released(self):
        """A target whose episodes are all unaired creates nothing."""
        unaired = timezone.now() + timedelta(days=30)
        for episode in self.episodes_metadata:
            episode["air_date"] = unaired

        created = self.season.watch_upto(TOTAL_EPISODES)

        self.assertEqual(created, 0)
        self.assertEqual(self.watched_episode_numbers(), [1, 2])
