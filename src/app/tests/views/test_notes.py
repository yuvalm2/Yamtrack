from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Item,
    MediaNote,
    MediaNoteKinds,
    MediaTypes,
    Sources,
)


class NotesViewTests(TestCase):
    """Test the notes and links modal and its save/delete endpoints."""

    def setUp(self):
        """Create a user, log in, and add an item to hang notes off."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/image.jpg",
        )

    def test_modal_lists_only_the_requesting_users_notes(self):
        """Another user's note on the same item is not shown."""
        other_credentials = {"username": "other", "password": "12345"}
        other_user = get_user_model().objects.create_user(**other_credentials)
        MediaNote.objects.create(user=self.user, item=self.item, body="mine")
        MediaNote.objects.create(user=other_user, item=self.item, body="theirs")

        response = self.client.get(
            reverse(
                "notes_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "238",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mine")
        self.assertNotContains(response, "theirs")

    def test_saving_a_note_stores_the_body(self):
        """A note is created against the posted item."""
        response = self.client.post(
            reverse("note_save"),
            {
                "item_id": self.item.id,
                "kind": MediaNoteKinds.NOTE.value,
                "body": "Watch the extended cut",
            },
        )

        self.assertEqual(response.status_code, 200)
        note = MediaNote.objects.get(user=self.user, item=self.item)
        self.assertEqual(note.kind, MediaNoteKinds.NOTE.value)
        self.assertEqual(note.body, "Watch the extended cut")

    def test_saving_a_link_stores_the_url(self):
        """A link is created and shown as a clickable anchor."""
        response = self.client.post(
            reverse("note_save"),
            {
                "item_id": self.item.id,
                "kind": MediaNoteKinds.LINK.value,
                "title": "Review",
                "url": "https://example.com/review",
            },
        )

        note = MediaNote.objects.get(user=self.user, item=self.item)
        self.assertEqual(note.kind, MediaNoteKinds.LINK.value)
        self.assertEqual(note.url, "https://example.com/review")
        self.assertContains(response, 'href="https://example.com/review"')

    def test_a_note_without_text_is_rejected(self):
        """The form requires the field its kind actually stores."""
        response = self.client.post(
            reverse("note_save"),
            {
                "item_id": self.item.id,
                "kind": MediaNoteKinds.NOTE.value,
                "body": "",
            },
        )

        self.assertEqual(MediaNote.objects.count(), 0)
        self.assertContains(response, "A note needs some text.")

    def test_a_link_without_a_url_is_rejected(self):
        """A link with no URL reports the error instead of saving."""
        response = self.client.post(
            reverse("note_save"),
            {
                "item_id": self.item.id,
                "kind": MediaNoteKinds.LINK.value,
                "title": "Review",
                "url": "",
            },
        )

        self.assertEqual(MediaNote.objects.count(), 0)
        self.assertContains(response, "A link needs a URL.")

    def test_a_url_in_a_note_body_is_linkified(self):
        """Urlize makes a pasted URL clickable without storing it as a link."""
        MediaNote.objects.create(
            user=self.user,
            item=self.item,
            body="see https://example.com/thread",
        )

        response = self.client.get(
            reverse(
                "notes_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "238",
                },
            ),
        )

        self.assertContains(response, 'href="https://example.com/thread"')

    def test_deleting_a_note_removes_it(self):
        """A user can delete their own note."""
        note = MediaNote.objects.create(
            user=self.user,
            item=self.item,
            body="temporary",
        )

        response = self.client.post(reverse("note_delete"), {"note_id": note.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(MediaNote.objects.count(), 0)

    def test_cannot_delete_another_users_note(self):
        """Deleting someone else's note is a 404 and leaves it in place."""
        other_credentials = {"username": "other", "password": "12345"}
        other_user = get_user_model().objects.create_user(**other_credentials)
        note = MediaNote.objects.create(
            user=other_user,
            item=self.item,
            body="theirs",
        )

        response = self.client.post(reverse("note_delete"), {"note_id": note.id})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(MediaNote.objects.count(), 1)

    def test_cannot_edit_another_users_note(self):
        """Posting someone else's note id does not overwrite their note."""
        other_credentials = {"username": "other", "password": "12345"}
        other_user = get_user_model().objects.create_user(**other_credentials)
        note = MediaNote.objects.create(
            user=other_user,
            item=self.item,
            body="theirs",
        )

        response = self.client.post(
            reverse("note_save"),
            {
                "item_id": self.item.id,
                "note_id": note.id,
                "kind": MediaNoteKinds.NOTE.value,
                "body": "hijacked",
            },
        )

        note.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(note.body, "theirs")
