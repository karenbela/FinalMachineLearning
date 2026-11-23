from pathlib import Path
import tempfile
import pandas as pd
import pytest
from core import validate,cluster,HALL_ROOMS,ValidationError
from prevention import action_plan,dataset_fingerprint,save_action,read_actions,join_actions

ROOT=Path(__file__).resolve().parents[1]

def sample():
    return validate(pd.read_csv(ROOT/'data/dummy_rooms.csv'))

def test_dataset_and_model():
    d=sample()
    assert len(d)==30
    assert d.room_id.is_unique
    assert all(r in HALL_ROOMS[h] for r,h in zip(d.room_id,d.hall))
    out,score,_,_,_=cluster(d,2)
    assert len(out)==30 and len(out.cluster.unique())==2
    assert -1<=score<=1

def test_action_plan_no_health_data():
    d=sample()
    plan=action_plan(d)
    assert set(plan.room_id).issubset(set(d.room_id))
    assert not {'chickenpox_reports','patient_name'}.intersection(plan.columns)
    assert plan.action_id.isin(['ventilation','interactions','facilities','occupants']).all()

@pytest.mark.parametrize(('column', 'value', 'message'), [
    ('room_id', 102.5, 'tidak sesuai hall'),
    ('occupant_count', 13.00001, 'bilangan bulat positif'),
])
def test_rejects_fractional_room_ids_and_counts(column, value, message):
    data = sample()
    data[column] = data[column].astype(float)
    data.loc[0, column] = value

    with pytest.raises(ValidationError, match=message):
        validate(data)

def test_persist_actions():
    d=sample(); plan=action_plan(d)
    item=plan.iloc[0]
    with tempfile.TemporaryDirectory() as tmp:
        db=Path(tmp)/'tasks.sqlite3'
        key=dataset_fingerprint(d)+'-k2'
        save_action(key,item.room_id,item.action_id,'Dalam proses','Pemeriksaan dijadwalkan',db)
        hist=read_actions(key,db)
        merged=join_actions(plan,hist)
        found=merged[(merged.room_id==item.room_id)&(merged.action_id==item.action_id)].iloc[0]
        assert found.status=='Dalam proses'
        assert found.note=='Pemeriksaan dijadwalkan'
        assert read_actions('other',db).empty
