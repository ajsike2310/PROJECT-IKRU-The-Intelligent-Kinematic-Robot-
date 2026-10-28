"""TC1-TC5: LLM response parsing. Technique: Equivalence Partitioning."""


def test_tc1_parse_segments_empty_input(parser):
    # Partition: empty / whitespace-only input
    assert parser.parse_segments("") == []
    assert parser.parse_segments("   ") == []


def test_tc2_parse_segments_explicit_emotion_tag(parser):
    # Partition: text carrying an explicit OLED emotion tag
    assert parser.parse_segments("[sad] I lost my ball") == [("sad", "I lost my ball")]


def test_tc3_parse_segments_infers_emotion_without_tag(parser):
    # Partition: untagged text -> emotion inferred from keywords
    assert parser.parse_segments("I am scanning the room") == [("focused", "I am scanning the room")]


def test_tc4_parse_llm_json_valid_and_malformed(parser):
    # Partition: valid JSON vs malformed JSON (falls back to the raw text)
    tools, text = parser.parse_llm_json('{"tools": [{"action": "dance", "duration": 3}], "response": "Watch me"}')
    assert tools == [{"action": "dance", "duration": 3}]
    assert text == "Watch me"
    assert parser.parse_llm_json("not json at all") == ([], "not json at all")


def test_tc5_parse_llm_json_strips_markdown_fence(parser):
    # Partition: JSON wrapped in a ```json code fence
    tools, text = parser.parse_llm_json('```json\n{"response": "Hello"}\n```')
    assert tools == []
    assert text == "Hello"


def test_stream_parser_splits_sentences_and_keeps_tags_intact(parser):
    sp = parser.StreamSentenceParser()
    out = []
    for token in ["Hello there. ", "[giggle] ", "How are you?"]:
        out += sp.feed(token)
    assert out == ["Hello there.", "[giggle] How are you?"]
    assert sp.flush() == []
