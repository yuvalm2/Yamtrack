"""Views for per-item text notes and links.

Kept in its own module rather than appended to views.py so that rebasing onto a
new upstream tag touches as little shared code as possible.
"""

import logging

from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from app.forms import MediaNoteForm
from app.models import Item, MediaNote
from app.providers import services

logger = logging.getLogger(__name__)


def get_or_create_item(media_type, media_id, source, season_number, episode_number):
    """Return the item for these coordinates, creating it from metadata if new."""
    try:
        return Item.objects.get(
            media_id=media_id,
            source=source,
            media_type=media_type,
            season_number=season_number,
            episode_number=episode_number,
        )
    except Item.DoesNotExist:
        metadata = services.get_media_metadata(
            media_type,
            media_id,
            source,
            [season_number],
            episode_number,
        )
        return Item.objects.create(
            media_id=media_id,
            source=source,
            media_type=media_type,
            season_number=season_number,
            episode_number=episode_number,
            title=metadata["title"],
            image=metadata["image"],
        )


def render_notes(request, item, form=None):
    """Render the notes modal body for an item."""
    return render(
        request,
        "app/components/fill_notes.html",
        {
            "item": item,
            "notes": MediaNote.objects.filter(user=request.user, item=item),
            "form": form if form is not None else MediaNoteForm(),
        },
    )


@require_GET
def notes_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
):
    """Return the modal listing the user's notes and links for an item."""
    item = get_or_create_item(
        media_type,
        media_id,
        source,
        season_number,
        episode_number,
    )
    return render_notes(request, item)


@require_POST
def note_save(request):
    """Create or update a note, then re-render the list in place."""
    item = get_object_or_404(Item, pk=request.POST["item_id"])
    note_id = request.POST.get("note_id")

    if note_id:
        instance = get_object_or_404(
            MediaNote,
            pk=note_id,
            user=request.user,
            item=item,
        )
    else:
        instance = MediaNote(user=request.user, item=item)

    form = MediaNoteForm(request.POST, instance=instance)
    if not form.is_valid():
        logger.error("Note form validation failed: %s", form.errors)
        return render_notes(request, item, form=form)

    note = form.save()
    logger.info("%s saved for %s", note, request.user)

    return render_notes(request, item)


@require_POST
def note_delete(request):
    """Delete one of the user's notes, then re-render the list in place."""
    note = get_object_or_404(MediaNote, pk=request.POST["note_id"], user=request.user)
    item = note.item
    note.delete()
    logger.info("Note deleted for %s", request.user)

    return render_notes(request, item)
