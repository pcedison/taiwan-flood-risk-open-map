from app.classifiers.taiwan_locations import extract_taiwan_location_terms


def test_extracts_taiwan_road_segments_from_news_title() -> None:
    terms = extract_taiwan_location_terms("台南安南區長溪路二段多處淹水，公學路也傳積水")

    assert "長溪路二段" in terms
    assert "公學路" in terms
    assert "安南區" in terms
