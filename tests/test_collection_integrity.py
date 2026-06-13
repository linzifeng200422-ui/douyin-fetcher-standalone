import json

from douyin_parser import (
    collection_incomplete_reason,
    collection_target_count,
    get_aweme_media_selection,
    is_completed_video_dir,
    merge_aweme_lists_by_id,
)
from external_backends import build_dy_downloader_config, dy_downloader_quality
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


def test_media_selection_prefers_original_landscape_ratio():
    aweme = {
        "video": {
            "width": 1440,
            "height": 1080,
            "play_addr": {
                "url_list": ["https://example.test/vertical.mp4"],
                "width": 1080,
                "height": 1920,
                "data_size": 1000,
            },
            "bit_rate": [
                {
                    "format": "mp4",
                    "bit_rate": 100,
                    "play_addr": {
                        "url_list": ["https://example.test/landscape.mp4"],
                        "width": 1440,
                        "height": 1080,
                        "data_size": 900,
                    },
                }
            ],
        }
    }

    selection = get_aweme_media_selection(aweme)

    assert selection["video_url"] == "https://example.test/landscape.mp4"
    assert selection["video_selection"]["width"] == 1440
    assert selection["video_selection"]["height"] == 1080


def test_media_selection_uses_video_dimensions_for_outer_play_addr():
    aweme = {
        "video": {
            "width": 1920,
            "height": 1080,
            "play_addr": {
                "url_list": ["https://example.test/outer-no-dimensions.mp4"],
                "data_size": 900,
            },
            "bit_rate": [
                {
                    "format": "mp4",
                    "gear_name": "normal_1080_0",
                    "quality_type": 1,
                    "bit_rate": 900000,
                    "play_addr": {
                        "url_list": ["https://example.test/cropped-portrait.mp4"],
                        "width": 1080,
                        "height": 1920,
                        "data_size": 5000,
                    },
                }
            ],
        }
    }

    selection = get_aweme_media_selection(aweme)

    assert selection["video_url"] == "https://example.test/outer-no-dimensions.mp4"
    assert selection["video_selection"]["width"] == 1920
    assert selection["video_selection"]["height"] == 1080


def test_media_selection_balanced_prefers_clearer_bitrate_over_lowest_1440():
    aweme = {
        "video": {
            "width": 1438,
            "height": 2556,
            "play_addr": {
                "url_list": ["https://example.test/default-1080.mp4"],
                "width": 1080,
                "height": 1920,
                "data_size": 5000,
            },
            "bit_rate": [
                {
                    "format": "mp4",
                    "gear_name": "normal_1080_0",
                    "quality_type": 1,
                    "bit_rate": 574153,
                    "play_addr": {
                        "url_list": ["https://example.test/default-1080.mp4"],
                        "width": 1080,
                        "height": 1920,
                        "data_size": 5222789,
                    },
                },
                {
                    "format": "mp4",
                    "gear_name": "adapt_lowest_1440_1",
                    "quality_type": 7,
                    "bit_rate": 373557,
                    "play_addr": {
                        "url_list": ["https://example.test/original-1438.mp4"],
                        "width": 1438,
                        "height": 2556,
                        "data_size": 3398062,
                    },
                },
            ],
        }
    }

    selection = get_aweme_media_selection(aweme)

    assert selection["video_url"] == "https://example.test/default-1080.mp4"
    assert selection["video_selection"]["width"] == 1080
    assert selection["video_selection"]["height"] == 1920


def test_media_selection_resolution_mode_prefers_exact_original_resolution():
    aweme = {
        "video": {
            "width": 1438,
            "height": 2556,
            "play_addr": {
                "url_list": ["https://example.test/default-1080.mp4"],
                "width": 1080,
                "height": 1920,
                "data_size": 5000,
            },
            "bit_rate": [
                {
                    "format": "mp4",
                    "gear_name": "normal_1080_0",
                    "quality_type": 1,
                    "bit_rate": 574153,
                    "play_addr": {
                        "url_list": ["https://example.test/default-1080.mp4"],
                        "width": 1080,
                        "height": 1920,
                        "data_size": 5222789,
                    },
                },
                {
                    "format": "mp4",
                    "gear_name": "adapt_lowest_1440_1",
                    "quality_type": 7,
                    "bit_rate": 373557,
                    "play_addr": {
                        "url_list": ["https://example.test/original-1438.mp4"],
                        "width": 1438,
                        "height": 2556,
                        "data_size": 3398062,
                    },
                },
            ],
        }
    }

    selection = get_aweme_media_selection(aweme, video_quality="resolution")

    assert selection["video_url"] == "https://example.test/original-1438.mp4"
    assert selection["video_selection"]["width"] == 1438
    assert selection["video_selection"]["height"] == 2556


def test_media_selection_landscape_filter_rejects_portrait_only_streams():
    aweme = {
        "video": {
            "width": 1080,
            "height": 1920,
            "play_addr": {
                "url_list": ["https://example.test/portrait.mp4"],
                "width": 1080,
                "height": 1920,
                "data_size": 5000,
            },
            "bit_rate": [
                {
                    "format": "mp4",
                    "gear_name": "normal_1080_0",
                    "quality_type": 1,
                    "bit_rate": 500000,
                    "play_addr": {
                        "url_list": ["https://example.test/portrait.mp4"],
                        "width": 1080,
                        "height": 1920,
                        "data_size": 5000,
                    },
                }
            ],
        }
    }

    selection = get_aweme_media_selection(aweme, video_orientation="landscape")

    assert selection["video_url"] == ""
    assert selection["video_selection"] == {}


def test_media_selection_landscape_filter_accepts_landscape_streams():
    aweme = {
        "video": {
            "width": 1080,
            "height": 1920,
            "play_addr": {
                "url_list": ["https://example.test/portrait.mp4"],
                "width": 1080,
                "height": 1920,
                "data_size": 5000,
            },
            "bit_rate": [
                {
                    "format": "mp4",
                    "gear_name": "normal_1080_0",
                    "quality_type": 1,
                    "bit_rate": 500000,
                    "play_addr": {
                        "url_list": ["https://example.test/portrait.mp4"],
                        "width": 1080,
                        "height": 1920,
                        "data_size": 5000,
                    },
                },
                {
                    "format": "mp4",
                    "gear_name": "normal_1080_0",
                    "quality_type": 1,
                    "bit_rate": 450000,
                    "play_addr": {
                        "url_list": ["https://example.test/landscape.mp4"],
                        "width": 1920,
                        "height": 1080,
                        "data_size": 4500,
                    },
                },
            ],
        }
    }

    selection = get_aweme_media_selection(aweme, video_orientation="landscape")

    assert selection["video_url"] == "https://example.test/landscape.mp4"


def test_dy_downloader_config_keeps_cookie_out_of_temp_config(tmp_path):
    config = build_dy_downloader_config(
        url="https://www.douyin.com/video/123",
        output_dir=tmp_path,
        count_limit=None,
        thread=3,
        video_quality="resolution",
    )

    assert config["link"] == ["https://www.douyin.com/video/123"]
    assert config["path"] == str(tmp_path)
    assert config["number"]["post"] == 0
    assert config["thread"] == 3
    assert config["video_quality"] == "1440p"
    assert config["download_pinned"] is True
    assert "cookie" not in config
    assert "cookies" not in config


def test_dy_downloader_quality_mapping():
    assert dy_downloader_quality("balanced") == "1440p"
    assert dy_downloader_quality("bitrate") == "highest"
    assert dy_downloader_quality("resolution") == "1440p"
    assert dy_downloader_quality("h264") == "1080p"
