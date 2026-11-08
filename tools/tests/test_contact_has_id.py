"""A real bounded contact is persisted by the production run recorder."""

import copy
import json

import pytest


def assert_contact_ids(rows, casualty_ids):
    contacts = [row for row in rows if row.get('topic') == 'casualty/contact']
    assert contacts, 'real log contains no casualty/contact records'
    for index, row in enumerate(contacts):
        data = row['data']
        assert 'id' in data, f'contact {index} missing casualty id'
        assert isinstance(data['id'], str) and data['id'].strip(), f'contact {index} invalid casualty id'
        assert data['id'] in casualty_ids, f'contact {index} names an unknown casualty id'


@pytest.fixture(scope='module')
def contact_log(tmp_path_factory):
    pytest.importorskip('mujoco')
    from sim.recorder import Recorder
    from sim.world import World
    from voice.contact import Contact

    world = World(render=False)
    # Same real scene and audible room as sim/tests/test_casualty_reply.py.
    world._set_pose((1.6, 0.73), 0.0)
    ids = {name for name, _, _ in world.casualties}
    cid = world.casualties[0][0]
    contact = Contact(gem=False, clock=lambda: world.t)
    path = tmp_path_factory.mktemp('contact-log') / 'contact.jsonl'
    recorder = Recorder(path, world)
    # Start a bounded conversation with a known scene casualty, not a fake contact.
    out = contact.on_casualties([{'id': cid, 'confidence': 0.9}])
    try:
        for _ in range(40):
            for topic, data in out:
                recorder.write(topic, data)
                if topic == 'say':
                    world.on_say(data)
            if contact.sessions[cid].status != 'talking':
                break
            out = []
            for _ in range(20):
                for topic, data in world.tick(0.1):
                    if topic == 'casualty/reply':
                        recorder.write(topic, data)
                        out += contact.hear(data)
            out += contact.tick()
        else:
            pytest.fail('real contact did not finish within its bounded conversation')
    finally:
        recorder.close()
    assert contact.sessions[cid].status == 'done'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(row['topic'] == 'casualty/reply' for row in rows), 'no real scene replies'
    return rows, ids


def test_every_real_contact_names_a_casualty(contact_log):
    rows, ids = contact_log
    assert_contact_ids(rows, ids)
    contacts = [row['data'] for row in rows if row['topic'] == 'casualty/contact']
    assert {row['status'] for row in contacts} >= {'talking', 'done'}


@pytest.mark.parametrize('mutation', ['missing', 'empty', 'numeric', 'unknown'])
def test_bad_contact_id_is_rejected(contact_log, mutation):
    rows, ids = contact_log
    rows = copy.deepcopy(rows)
    contacts = [row for row in rows if row.get('topic') == 'casualty/contact']
    data = contacts[-1]['data']  # Check later contacts too, not just the first.
    if mutation == 'missing':
        del data['id']
        message = 'missing casualty id'
    elif mutation == 'unknown':
        data['id'] = 'not-a-scene-casualty'
        message = 'unknown casualty id'
    else:
        data['id'] = '' if mutation == 'empty' else 1
        message = 'invalid casualty id'
    with pytest.raises(AssertionError, match=message):
        assert_contact_ids(rows, ids)
