"""Administrative screening suggestions, NOT epidemiological risk scores."""
import hashlib
import sqlite3
from pathlib import Path
import pandas as pd

DB_PATH=Path(__file__).resolve().parent/'actions.sqlite3'

ACTION_CATALOG={
 'ventilation': ('Periksa bukaan udara','Data menunjukkan bukaan udara di kamar ini terbatas.','Cek jendela dan lubang angin. Minta bantuan teknisi bila perlu.'),
 'interactions': ('Cek kegiatan antarkamar','Penghuni kamar ini lebih sering berinteraksi dengan penghuni kamar lain dibandingkan kebanyakan kamar yang tercatat.','Jelaskan gejala cacar air dan cara melapor jika ada penghuni yang sakit.'),
 'facilities': ('Cek ruang bersama','Penghuni kamar ini lebih sering memakai fasilitas bersama dibandingkan kebanyakan kamar yang tercatat.','Cek kegiatan di ruang bersama dan ingatkan penghuni tentang langkah pencegahan.'),
 'occupants': ('Cek jumlah penghuni','Jumlah penghuni kamar ini lebih banyak dibandingkan kebanyakan kamar yang tercatat.','Cek berapa orang yang dapat ditampung kamar dan kondisi tempat tidurnya.'),
}


def dataset_fingerprint(df):
    cols=['room_id','hall','occupant_count','interaction_frequency','shared_facility_frequency','ventilation_score']
    ordered=df[cols].sort_values('room_id').reset_index(drop=True)
    return hashlib.sha256(ordered.to_csv(index=False).encode()).hexdigest()[:16]


def action_plan(df):
    """Specific room screening signals, not a medically validated risk ranking."""
    q_inter=df.interaction_frequency.quantile(.75)
    q_fac=df.shared_facility_frequency.quantile(.75)
    q_occ=df.occupant_count.quantile(.75)
    signals=[]
    for row in df.itertuples(index=False):
        checks=[]
        if int(row.ventilation_score)==0:checks.append('ventilation')
        if float(row.interaction_frequency)>q_inter:checks.append('interactions')
        if float(row.shared_facility_frequency)>q_fac:checks.append('facilities')
        if float(row.occupant_count)>q_occ:checks.append('occupants')
        for check in checks:
            title,why,next_action=ACTION_CATALOG[check]
            signals.append({'room_id':int(row.room_id),'hall':row.hall,'action_id':check,
                            'pemeriksaan':title,'alasan':why,'tindakan':next_action})
    return pd.DataFrame(signals,columns=['room_id','hall','action_id','pemeriksaan','alasan','tindakan'])


def init_db(path=DB_PATH):
    con=sqlite3.connect(path)
    con.execute('''CREATE TABLE IF NOT EXISTS action_tracking (
        dataset_key TEXT NOT NULL, room_id INTEGER NOT NULL, action_id TEXT NOT NULL,
        status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(dataset_key,room_id,action_id))''')
    con.commit();con.close()


def save_action(dataset_key,room_id,action_id,status,note='',path=DB_PATH):
    allowed={'Belum ditinjau','Dalam proses','Selesai','Tidak berlaku'}
    if status not in allowed:raise ValueError('Status tidak dikenal')
    if action_id not in ACTION_CATALOG:raise ValueError('Jenis tindakan tidak dikenal')
    init_db(path)
    con=sqlite3.connect(path)
    con.execute('''INSERT INTO action_tracking(dataset_key,room_id,action_id,status,note,updated_at)
        VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(dataset_key,room_id,action_id) DO UPDATE SET
        status=excluded.status, note=excluded.note, updated_at=CURRENT_TIMESTAMP''',
        (str(dataset_key),int(room_id),action_id,status,str(note)[:500]))
    con.commit();con.close()


def read_actions(dataset_key,path=DB_PATH):
    init_db(path)
    con=sqlite3.connect(path)
    d=pd.read_sql_query('SELECT room_id,action_id,status,note,updated_at FROM action_tracking WHERE dataset_key=?',con,params=(str(dataset_key),))
    con.close();return d


def join_actions(plan,history):
    if plan.empty:
        return plan.assign(status=pd.Series(dtype='str'),note=pd.Series(dtype='str'))
    if history.empty:
        return plan.assign(status='Belum ditinjau',note='')
    merged=plan.merge(history[['room_id','action_id','status','note']],on=['room_id','action_id'],how='left')
    merged['status']=merged.status.fillna('Belum ditinjau')
    merged['note']=merged.note.fillna('')
    return merged
