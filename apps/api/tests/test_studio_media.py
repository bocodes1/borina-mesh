"""Stop media (M5): only files inside projects/<slug>/ ever reach Telegram."""
import json
import os

import pytest

from dispatch import studio_media as sm

BO = 6452258223
PNG = b"\x89PNG\r\n\x1a\nfake"
SECRET = b"-----BEGIN OPENSSH PRIVATE KEY----- fake"


@pytest.fixture
def studio(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_DIR", str(tmp_path))
    project = tmp_path / "projects" / "sample-desk"
    (project / "look").mkdir(parents=True)
    (project / "kit").mkdir()
    posts = []
    monkeypatch.setattr(sm, "post", lambda method, data, files: posts.append({"method": method, "data": data, "files": files}) or {"ok": True})
    return tmp_path, project, posts


def stop(images, video=None, slug="sample-desk"):
    return {"id": "look-1", "slug": slug, "title": "Pick a look", "body": "", "images": images, "video": video,
            "options": [{"id": "a", "label": "Look A"}], "costUsd": None}


def test_one_image_is_a_photo(studio):
    _, project, posts = studio
    (project / "look" / "a.png").write_bytes(PNG)
    assert sm.send_stop_media(BO, stop([str(project / "look" / "a.png")])) == 0
    assert [p["method"] for p in posts] == ["sendPhoto"] and posts[0]["data"]["chat_id"] == str(BO)


def test_several_images_are_one_album_and_the_video_follows(studio):
    _, project, posts = studio
    for n in ("a", "b"):
        (project / "look" / f"{n}.png").write_bytes(PNG)
    (project / "kit" / "demo.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    sm.send_stop_media(BO, stop([str(project / "look" / "a.png"), str(project / "look" / "b.png")], str(project / "kit" / "demo.mp4")))
    assert [p["method"] for p in posts] == ["sendMediaGroup", "sendVideo"]
    assert [m["media"] for m in json.loads(posts[0]["data"]["media"])] == ["attach://p0", "attach://p1"]


def test_paths_outside_the_project_are_never_uploaded(studio):
    root, project, posts = studio
    secret = root / "id_ed25519.png"
    secret.write_bytes(SECRET)
    other = root / "projects" / "other-desk"
    other.mkdir(parents=True)
    (other / "x.png").write_bytes(SECRET)
    os.symlink(secret, project / "look" / "link.png")
    bad = [str(secret), str(project / ".." / "other-desk" / "x.png"), str(project / "look" / "link.png"),
           "projects/sample-desk/look/a.png"]
    assert sm.send_stop_media(BO, stop(bad, str(secret))) == 5
    assert posts == []


def test_wrong_types_and_oversize_files_are_skipped(studio):
    _, project, posts = studio
    (project / "look" / "notes.txt").write_bytes(b"x")
    big = project / "look" / "big.png"
    with big.open("wb") as fh:
        fh.truncate(sm.PHOTO_MAX_BYTES + 1)
    assert sm.send_stop_media(BO, stop([str(project / "look" / "notes.txt"), str(big)])) == 2
    assert posts == []


def test_a_bad_slug_sends_nothing(studio):
    _, _, posts = studio
    assert sm.send_stop_media(BO, stop([], slug="../etc")) == 1 and posts == []


def test_an_upload_error_is_counted_not_raised(studio, monkeypatch):
    _, project, _ = studio
    (project / "look" / "a.png").write_bytes(PNG)

    def boom(*_a):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(sm, "post", boom)
    assert sm.send_stop_media(BO, stop([str(project / "look" / "a.png")])) == 1
