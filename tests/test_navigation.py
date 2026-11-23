from pathlib import Path

from streamlit.testing.v1 import AppTest

import prevention

ROOT = Path(__file__).resolve().parents[1]


def assert_room_page(app, expected_room):
    assert not app.exception
    assert app.radio(key='page_nav').value == '🔎 Pemeriksaan Kamar'
    assert app.selectbox(key='room_select').value == expected_room


def test_room_navigation(monkeypatch, tmp_path):
    database = tmp_path / 'actions.sqlite3'
    read_actions = prevention.read_actions
    monkeypatch.setattr(prevention, 'read_actions', lambda key: read_actions(key, database))
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
    assert not app.exception

    app.button(key='goto_room').click().run()
    assert_room_page(app, 101)
    app.selectbox(key='room_select').select(103).run()
    assert_room_page(app, 103)

    app.radio(key='page_nav').set_value('🏠 Beranda').run()
    app.selectbox(key='home_room').select(102).run()
    app.button(key='home_goto_room').click().run()
    assert_room_page(app, 102)
    assert [metric.value for metric in app.metric] == ['4', '10.5', '13.5', '1']
    assert any(
        '**Cluster ' in message.value and 'Dibandingkan rata-rata' in message.value
        for message in app.info
    )
    compare = next(button for button in app.button if button.label == 'Lihat hasil simulasi')
    compare.click().run()
    assert_room_page(app, 102)
    assert any('kamar tetap paling mirip dengan Kelompok' in message.value for message in app.info)

    app.radio(key='page_nav').set_value('🗺️ Peta Kamar').run()
    app.button(key='map_101').click().run()
    assert_room_page(app, 101)
    assert any('Data kamar ini belum tersedia' in message.value for message in app.info)

    for page in ('🛡️ Tindakan Pencegahan', '✨ Analisis AI', '📑 Laporan'):
        app.radio(key='page_nav').set_value(page).run()
        assert not app.exception

    app.radio(key='page_nav').set_value('✨ Analisis AI').run()
    app.select_slider(key='cluster_k').set_value(3).run()
    assert not app.exception
    profiles = [element.value for element in app.markdown if element.value.startswith('**Cluster ')]
    assert len(profiles) == 3
