import json

from douyin_parser import (
    collection_incomplete_reason,
    collection_target_count,
    is_completed_video_dir,
    merge_aweme_lists_by_id,
)
from get_cookie import has_login_cookie


def test_all_requires_profile_total_to_match():
    reason = collection_incomplete_reason(
        21,
        expected_count=221,
        count_limit=None,
        has_more=False,
    )
    assert "主页显示 221 个作品" in reason
    assert collection_incomplete_reason(
        221,
        expected_count=221,
        count_limit=None,
        has_more=False,
    ) == ""


def test_finite_count_uses_lower_target():
    assert collection_target_count(expected_count=221, count_limit=1) == 1
    assert collection_incomplete_reason(
        1,
        expected_count=221,
        count_limit=1,
        has_more=True,
    ) == ""


def test_merge_prefers_extra_items_and_order():
    merged = merge_aweme_lists_by_id(
        [{"aweme_id": "1", "desc": "old"}, {"aweme_id": "2", "desc": "two"}],
        [{"aweme_id": "1", "desc": "new"}, {"aweme_id": "3", "desc": "three"}],
        preferred_order=["3", "1", "2"],
    )
    assert [item["aweme_id"] for item in merged] == ["3", "1", "2"]
    assert merged[1]["desc"] == "new"


def test_completed_dir_requires_video_audio_and_success_status(tmp_path):
    video_dir = tmp_path / "sample"
    video_dir.mkdir()
    (video_dir / "collection-status.json").write_text(
        json.dumps({"status": "success"}),
        encoding="utf-8",
    )
    (video_dir / "audio.mp3").write_bytes(b"audio")
    assert not is_completed_video_dir(video_dir)

    (video_dir / "video.mp4").write_bytes(b"video")
    assert is_completed_video_dir(video_dir)


def test_cookie_login_detection_rejects_visitor_cookie():
    assert not has_login_cookie([
        {"name": "ttwid", "value": "x"},
        {"name": "odin_tt", "value": "y"},
    ])
    assert has_login_cookie([
        {"name": "sessionid_ss", "value": "logged-in"},
    ])
