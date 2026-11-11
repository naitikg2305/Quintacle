from quintacle_core.nodes.kb.chat_store import ChatStore


def make_store(tmp_path):
    return ChatStore(tmp_path / "kb_chats")


def test_save_then_load_round_trip(tmp_path):
    store = make_store(tmp_path)
    session_id = store.create("Deadlift form thoughts")
    store.save(
        session_id,
        "Deadlift form thoughts",
        [
            {"role": "user", "content": "why do I round my back on heavy reps?"},
            {"role": "assistant", "content": "Probably not bracing before the pull."},
        ],
    )

    messages = store.load(session_id)

    assert messages == [
        {"role": "user", "content": "why do I round my back on heavy reps?"},
        {"role": "assistant", "content": "Probably not bracing before the pull."},
    ]


def test_list_sessions_shows_title_and_newest_first(tmp_path):
    store = make_store(tmp_path)
    store.create("First chat")
    id2 = store.create("Second chat")

    sessions = store.list_sessions()

    assert sessions[0]["id"] == id2
    assert {s["title"] for s in sessions} == {"First chat", "Second chat"}


def test_delete_removes_the_file(tmp_path):
    store = make_store(tmp_path)
    session_id = store.create("Temp")
    store.delete(session_id)

    assert store.load(session_id) == []
    assert session_id not in [s["id"] for s in store.list_sessions()]


def test_multiline_message_content_round_trips(tmp_path):
    store = make_store(tmp_path)
    session_id = store.create("Multiline")
    store.save(
        session_id,
        "Multiline",
        [{"role": "user", "content": "line one\nline two\n\nline four"}],
    )

    assert store.load(session_id) == [{"role": "user", "content": "line one\nline two\n\nline four"}]


def test_attachment_content_blocks_collapse_to_text_on_save(tmp_path):
    store = make_store(tmp_path)
    session_id = store.create("With attachment")
    store.save(
        session_id,
        "With attachment",
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what's in this photo?"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}},
                ],
            },
            {"role": "assistant", "content": "Looks like a receipt."},
        ],
    )

    messages = store.load(session_id)

    assert messages[0]["content"] == "what's in this photo?\n📎 (photo attached)"
    assert messages[1]["content"] == "Looks like a receipt."


def test_markdown_heading_in_message_body_survives_round_trip(tmp_path):
    """Regression: load() used to treat ANY line starting with '# ' as the
    session title and silently drop it — fine when replies were plain text,
    but Tier 1 markdown rendering means the model routinely opens a reply
    with a real heading, which must not vanish on reload."""
    store = make_store(tmp_path)
    session_id = store.create("Trip planning")
    store.save(
        session_id,
        "Trip planning",
        [{"role": "assistant", "content": "# Portugal Itinerary\n\nDay 1: Lisbon"}],
    )

    messages = store.load(session_id)

    assert messages == [{"role": "assistant", "content": "# Portugal Itinerary\n\nDay 1: Lisbon"}]
