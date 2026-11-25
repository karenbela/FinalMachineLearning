from pathlib import Path
from app.logic import decode_file,validate_row,cluster_data
import csv
import pytest

ROOT=Path(__file__).resolve().parents[2]
def test_original_import_dummy_all_rows_validate():
    rows=decode_file((ROOT/'samples'/'import_dummy_63_kamar.csv').read_bytes(),'data.csv')
    assert len(rows)==315
    assert not [(i,e) for i,r in enumerate(rows) if (e:=validate_row(r))]

def test_duplicate_or_wrong_consent_rejected():
    rows=decode_file((ROOT/'samples'/'import_dummy_63_kamar.csv').read_bytes(),'data.csv')
    r=dict(rows[0]);r['consent_status']='TIDAK_SETUJU'
    assert 'persetujuan belum diberikan' in validate_row(r)

def test_kmeans_three_groups_from_original_synthetic_features():
    with open(ROOT/'samples'/'rekap_dummy_63_kamar.csv',encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    result=cluster_data(rows)
    assert len(rows)==len(result['labels'])==63
    assert len(set(result['labels']))==3
    assert sum(c['rooms'] for c in result['centroids'])==63
    assert 0<=result['silhouette']<=1
    assert 'bukan' in result['interpretation_note'].lower()

def test_bad_upload_extension():
    with pytest.raises(ValueError):decode_file(b'hello','random.exe')
