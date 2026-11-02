import collections

from rumble.content import get_world, world_keys
from rumble.content.expansion import ADDITIONS
from rumble.content.validate import validate_bank_lines
from rumble.engine import Game, Settings


def game(n, seed=1, **kwargs):
    return Game(get_world('garage'), [(i, f'p{i}') for i in range(n)], Settings(**kwargs), seed=seed)


def test_small_lobbies_finish_without_padding():
    for n, bound in [(2, 2), (3, 3), (4, 4), (5, 4)]:
        for seed in range(40):
            g = game(n, seed)
            g.run_all()
            assert g.round_no <= bound
            assert g.total_rounds == g.round_no
            assert not any(not rd.eliminated for rd in g.history[1:])


def test_automatic_second_chance_is_once_per_member_and_game():
    for seed in range(40):
        g = game(20, seed, revive_rate=0.5)
        while not g.finished:
            rd = g.next_round()
            if rd.second_chance:
                _, uid = g.resolve_auto_second_chance()
                assert uid is not None and g.players[uid].alive
                assert g.resolve_auto_second_chance()[1] is None
        assert all(p.revives <= 1 for p in g.players.values())
        assert sum(p.revives for p in g.players.values()) <= g.revive_cap + 1
    g = game(5)
    g.run_all()
    assert not g.second_chance_done


def test_hazards_off_means_off_including_crowded_final():
    for seed in range(25):
        g = game(250, seed, hazards=False, min_rounds=2, max_rounds=2)
        g.run_all()
        assert all('hazard' not in rd.kinds for rd in g.history)
        assert g.alive_ids() == [g.winner]


def test_identity_transfer_and_bound_callback():
    transfers = callbacks = 0
    for seed in range(60):
        g = game(35, seed)
        while not g.finished:
            previous_ids = dict(g.item_ids)
            previous_items = dict(g.items)
            rd = g.next_round()
            for event in rd.events:
                if event.kind == 'transfer':
                    holder, recipient = event.actors
                    assert g.item_ids[recipient] == previous_ids[holder]
                    assert g.items[recipient] == previous_items[holder]
                    assert holder not in g.item_ids
                    transfers += 1
                if event.kind == 'call':
                    assert event.actors[0] in previous_items
                    assert previous_items[event.actors[0]] in event.text
                    callbacks += 1
            assert set(g.items) == set(g.item_ids)
            assert len(set(g.item_ids.values())) == len(g.item_ids)
            assert all(g.players[p].alive for p in g.items)
            if rd.second_chance:
                g.resolve_auto_second_chance()
    assert transfers and callbacks


def test_same_event_victims_share_rank():
    g = game(5)
    g.round_no = 1
    g._event_group = 1
    g._eliminate(0)
    g._eliminate(1)
    places = g.ranking_places()
    assert places[0] == places[1]


def test_cross_game_recent_ids_are_avoided_when_pool_has_fresh_lines():
    w = get_world('garage')
    target = w.pools['wipe'][0]
    recent = [line.id for line in w.pools['wipe'] if line.id != target.id]
    g = Game(w, [(0, 'a'), (1, 'b')], seed=3, recent_line_ids=recent)
    assert g._pick('wipe').id == target.id


def test_curated_scenes_have_executable_contracts_and_brand():
    assert sum(len(rows) for kinds in ADDITIONS.values() for rows in kinds.values()) == 48
    for world, kinds in ADDITIONS.items():
        for kind, rows in kinds.items():
            for row in rows:
                issues = []
                validate_bank_lines(kind, row, row['source_id'], issues)
                assert not issues
                assert 'toy' not in row['text'].lower().split()
    for world in world_keys():
        if world != 'nft':
            assert all('onchain' not in line.tags for pool in get_world(world).pools.values() for line in pool)
    assert all('modern' not in line.tags for pool in get_world('redline').pools.values() for line in pool)


def test_one_capsule_per_game_and_actor_accounting():
    for seed in range(40):
        g = game(60, seed)
        g.run_all()
        assert sum(e.line_id == 'x.garage.survive.2' for rd in g.history for e in rd.events) <= 1
        for rd in g.history:
            seen = collections.Counter(a for e in rd.events for a in e.actors)
            assert all(count == 1 for count in seen.values())


def test_small_message_budget_does_not_accumulate_a_crowded_final():
    for lines in (6, 8, 12, 20):
        for hazards in (False, True):
            for seed in range(20):
                g = game(250, seed, max_lines=lines, hazards=hazards, min_rounds=2, max_rounds=2)
                g.run_all()
                assert max(len(rd.events) for rd in g.history) <= lines
                assert len(g.alive_ids()) == 1
