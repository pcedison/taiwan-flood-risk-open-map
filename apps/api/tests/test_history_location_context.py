from __future__ import annotations

from app.domain.history import nearest_public_news_location_context, nearest_public_news_location_text


def test_nearest_public_news_location_text_uses_preferred_user_text() -> None:
    assert (
        nearest_public_news_location_text(
            lat=22.65646,
            lng=120.32574,
            radius_m=500,
            preferred_text="三民區本和里大豐一路",
        )
        == "三民區本和里大豐一路"
    )


def test_nearest_public_news_location_context_uses_bundled_village_data() -> None:
    context = nearest_public_news_location_context(
        lat=22.65646,
        lng=120.32574,
        radius_m=500,
    )

    assert context is not None
    assert context.name == "高雄市三民區本和里"
    assert context.distance_m < 10
    assert context.source_key == "moi-village-boundary-twd97-geographic"
