import pytest

from rumble.content import get_world
from rumble.content.validate import validate_bank_lines
from rumble.engine import Game, Settings
from rumble.text import reading_pause
from tools.verify_experience import CheckedGame, distribution, play, series_check


@pytest.mark.parametrize('text,world,tagged,error', [
    ('{A} brings the race car into the pits.', 'gulf', True, False),
    ('{A} watches the race cars enter the pits.', 'gulf', True, False),
    ('{A} brings the Hot Wheels car into the pits.', 'gulf', True, True),
    ('{A} brings the hot wheels cars into the pits.', 'gulf', True, True),
    ('{A} watches the cars enter the pits.', 'garage', False, True),
    ('{A} watches the race car enter the pits.', 'garage', True, False),
])
def test_real_vehicle_context_does_not_rename_hot_wheels(text, world, tagged, error):
    issues = []
    validate_bank_lines('survive', dict(text=text, tags=['real_vehicle'] if tagged else []),
                        world + '.survive', issues)
    assert bool([issue for issue in issues if issue[0] == 'ERROR']) == error
    if not error:
        assert not issues


def test_second_chance_waits_for_sampled_round_and_checks_field():
    g = Game(get_world('garage'), [(i, f'p{i}') for i in range(8)], seed=3)
    g.second_chance_round = 3
    g.total_rounds = 6
    for pid in range(4):
        g._eliminate(pid)
    g.round_no = 2
    assert not g._second_chance_due()
    g.round_no = 3
    assert g._second_chance_due()
    _, uid = g.resolve_auto_second_chance()
    assert uid is not None and g.players[uid].revives == 1
    assert not g._second_chance_due()
    assert g.resolve_auto_second_chance()[1] is None


def test_observer_does_not_change_games_and_counts_item_final_payoff():
    finals = 0
    for seed in range(30):
        players = [(i, f'p{i}') for i in range(5)]
        reference = Game(get_world('garage'), players, seed=seed)
        reference.run_all()
        observed = CheckedGame(get_world('garage'), players, seed=seed)
        result = play(observed)
        assert observed.history == reference.history
        assert observed.summary() == reference.summary()
        assert observed.win_text == reference.win_text
        assert result['items_recalled'] >= result['item_final_count']
        assert result['items_found'] == result['items_recalled'] + result['items_dropped_without_recall']
        finals += result['item_final_count']
    assert finals > 0


def test_long_names_fit_rendered_messages():
    g = CheckedGame(get_world('gulf'), [(i, str(i) + '\u0646' * 60) for i in range(250)],
                    Settings(max_lines=20), seed=8)
    assert play(g)['rounds'] > 1


def test_percentiles_do_not_hide_tail():
    result = distribution(list(range(1, 101)))
    assert result == dict(mean=50.5, min=1, p50=50, p95=95, max=100)
    assert distribution([]) is None


async def test_ten_game_series_uses_persisted_history(tmp_path):
    rows = await series_check(tmp_path)
    assert len(rows) == 6
    assert all(row['games'] == 10 for row in rows)
    assert sum(row['recent_hits'] for row in rows) < sum(row['baseline_recent_hits'] for row in rows)
    assert (tmp_path / 'series_transcripts.txt').is_file()


def test_reading_pause_respects_host_minimum_and_caps_dense_rounds():
    assert reading_pause('short lap', 10) == 10
    assert reading_pause('word ' * 60, 10) == 20
    assert reading_pause('word ' * 1000, 10) == 30
    assert reading_pause('word ' * 1000, 60) == 60


async def test_runner_gives_dense_rounds_more_time(tmp_path):
    from tests.test_durable_results import make_runner
    env = await make_runner(tmp_path, 'reading-pace', n=60)
    sleeps = []
    original = env.runner.clock.sleep

    async def record_sleep(seconds):
        sleeps.append(seconds)
        await original(seconds)

    env.runner.clock.sleep = record_sleep
    try:
        await env.runner.run()
        assert env.runner.state == 'finished'
        assert any(10 < seconds <= 30 for seconds in sleeps)
    finally:
        await env.db.close()
