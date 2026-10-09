"""Stop watcher + answers (M5): each stop carded once, never answered by the
mesh, money needs a second tap, and notes ride along with an answer."""
import json

import pytest

import routes.telegram as tg
from dispatch import builder, dispatcher, studio_media, studio_stops
from tests.fakes.studio import BO, buttons, clean_tables, install, tap


def stop(id="look-1", cost=None, options=(("a", "Look A"), ("b", "Look B"), ("redo", "Redo"))):
    return {"version": 1, "id": id, "slug": "sample-desk", "kind": "look" if cost is None else "cost",
            "title": "Pick a look" if cost is None else "Buy logo credits",
            "body": "Two hero directions are on staging.", "images": [], "video": None,
            "options": [{"id": i, "label": label} for i, label in options], "costUsd": cost,
            "createdAt": "2026-10-09T16:00:00.000Z"}


@pytest.fixture
def studio(monkeypatch, tmp_path):
    env = install(monkeypatch, tmp_path)
    env.media = []
    monkeypatch.setattr(studio_media, "send_stop_media", lambda chat, st: env.media.append(st["id"]) or 0)

    def pending(*stops):
        env.cli.reply("stops", 0, json.dumps({"stops": list(stops)}) + "\n")

    env.pending = pending
    yield env
    clean_tables()


def _card(env):
    return [m for m in env.sent if m["reply_markup"]][-1]


def _reply(message_id, text):
    return tg.process_update({"update_id": 77, "message": {"chat": {"id": BO}, "text": text,
                                                           "reply_to_message": {"message_id": message_id}}})


def test_each_stop_is_carded_once_with_its_media_first(studio):
    studio.pending(stop())
    assert studio_stops.watch_stops() == {"status": "ok", "sent": 1}
    assert studio.media == ["look-1"]
    card = _card(studio)
    assert "sample-desk · Pick a look" in card["text"]
    assert [label for label, _ in buttons(card)] == ["Look A", "Look B", "Redo"]
    assert studio_stops.watch_stops() == {"status": "ok", "sent": 0}
    assert dispatcher.find_thread(BO, card["message_id"]).agent_id == "studio"


def test_the_watcher_never_answers_and_survives_a_broken_cli(studio):
    studio.cli.reply("stops", 1, "Error: boom\n")
    assert studio_stops.watch_stops() == {"status": "cli_error"}
    studio.pending(stop(), {**stop(id="x"), "slug": "../evil"})
    studio_stops.watch_stops()
    assert "answer" not in studio.cli.subcommands() and studio.spawned == []
    assert len([m for m in studio.sent if m["reply_markup"]]) == 1


def test_a_tap_answers_by_telegram_and_resumes_the_run_once(studio):
    studio.pending(stop())
    studio_stops.watch_stops()
    a, b, _redo = [d for _, d in buttons(_card(studio))]
    studio.cli.reply("answer", 0, "ANSWERED sample-desk look-1 b\n")
    assert tap(b)["status"] == "studio_answered"
    assert studio.cli.calls[-1] == ["answer", "sample-desk", "look-1", "b", "--by", "telegram"]
    assert tap(b)["toast"] == "Already done" and tap(a)["toast"] == "Already done"
    assert studio.cli.subcommands().count("answer") == 1 and studio.spawned == ["sample-desk"]


def test_money_needs_a_second_tap(studio):
    studio.pending(stop(id="cost-1", cost=12.5, options=(("yes", "Yes"), ("no", "No"))))
    studio_stops.watch_stops()
    card = _card(studio)
    assert "$12.50" in card["text"]
    yes = buttons(card)[0][1]
    assert tap(yes)["status"] == "studio_confirm_asked"
    assert tap(yes)["status"] == "studio_confirm_asked"  # a double tap still only asks
    assert "answer" not in studio.cli.subcommands()
    confirm_card = _card(studio)
    assert "Spend $12.50?" in confirm_card["text"]
    (label, confirm), (_, cancel) = buttons(confirm_card)
    assert label == "Confirm $12.50"
    studio.cli.reply("answer", 0, "ANSWERED sample-desk cost-1 yes\n")
    assert tap(confirm)["status"] == "studio_answered"
    assert studio.cli.calls[-1][:4] == ["answer", "sample-desk", "cost-1", "yes"]
    assert tap(yes)["toast"] == "Already done" and tap(cancel)["toast"] == "Already done"
    assert studio.cli.subcommands().count("answer") == 1


def test_cancel_spends_nothing_and_no_answers_directly(studio):
    studio.pending(stop(id="cost-1", cost=12.5, options=(("yes", "Yes"), ("no", "No"))))
    studio_stops.watch_stops()
    yes, no = [d for _, d in buttons(_card(studio))]
    tap(yes)
    confirm, cancel = [d for _, d in buttons(_card(studio))]
    assert tap(cancel)["toast"] == "Cancelled" and "answer" not in studio.cli.subcommands()
    assert tap(confirm)["toast"] == "Already done"
    studio.cli.reply("answer", 0, "ANSWERED sample-desk cost-1 no\n")
    assert tap(no)["status"] == "studio_answered"
    assert studio.cli.calls[-1][:4] == ["answer", "sample-desk", "cost-1", "no"]


def test_a_reply_is_a_note_even_when_it_reads_like_a_mesh_command(studio, monkeypatch):
    monkeypatch.setattr(builder, "start_build", lambda *a, **k: pytest.fail("a studio note must never start a mesh build"))
    studio.pending(stop())
    studio_stops.watch_stops()
    assert _reply(_card(studio)["message_id"], "Ship, but make the hero darker")["status"] == "studio_note"
    note_card = _card(studio)
    assert "Note: Ship, but make the hero darker" in note_card["text"]
    studio.cli.reply("answer", 0, "ANSWERED sample-desk look-1 redo\n")
    tap(buttons(note_card)[2][1])
    assert studio.cli.calls[-1] == ["answer", "sample-desk", "look-1", "redo", "--by", "telegram",
                                    "--note=Ship, but make the hero darker"]


def test_a_note_for_a_stop_that_is_no_longer_waiting(studio):
    studio.pending(stop())
    studio_stops.watch_stops()
    card = _card(studio)
    studio.pending()
    assert _reply(card["message_id"], "change the font")["status"] == "studio_note_stale"
    assert "isn't waiting any more" in studio.sent[-1]["text"]


def test_an_answer_made_elsewhere_retires_the_buttons(studio):
    studio.pending(stop())
    studio_stops.watch_stops()
    a, b, _redo = [d for _, d in buttons(_card(studio))]
    studio.cli.reply("answer", 1, "", "$ node --import tsx scripts/studio.ts answer sample-desk look-1 a --by telegram\n"
                     "studio answer: already answered\n[ELIFECYCLE] Command failed with exit code 1.\n")
    assert tap(a)["toast"] == "Already answered"
    assert tap(b)["toast"] == "Already done" and studio.spawned == []



def test_a_broken_watcher_is_said_once_and_so_is_its_recovery(studio):
    studio.cli.reply("stops", 1, "", "studio stops: boom\n")
    studio_stops.watch_stops()
    studio_stops.watch_stops()
    assert len(studio.sent) == 1 and "stop watcher" in studio.sent[0]["text"]
    studio.pending()
    studio_stops.watch_stops()
    studio_stops.watch_stops()
    assert len(studio.sent) == 2 and "working again" in studio.sent[-1]["text"]

def test_register_studio_stops_every_two_minutes(monkeypatch):
    from scheduler import SchedulerService

    monkeypatch.setenv("STUDIO_ENABLED", "1")
    svc = SchedulerService()
    svc.register_studio_stops()
    assert svc.list_schedules()["studio-stops"] == "*/2 * * * *"
