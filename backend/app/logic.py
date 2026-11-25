"""Pure validation helpers and unsupervised clustering. No clinical risk predictions."""
import csv, io, math
from datetime import datetime,date
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

FIELDS=['assessment_id','period','submitted_at','input_source','resident_code','resident_name','hall','room_id','stay_days_7d','varicella_history','last_varicella_year','history_verified','vaccine_doses_documented','vaccine_verified','close_interactions_7d','contact_case_21d','contact_date','contact_type','consent_status']
TRUTH={'YA':True,'TIDAK':False}

def decode_file(contents:bytes, filename:str):
    if len(contents)>5*1024*1024: raise ValueError('Ukuran file maksimal 5 MB.')
    name=filename.lower()
    if name.endswith('.csv'):
        try:
            content=contents.decode('utf-8-sig')
        except UnicodeDecodeError as exc: raise ValueError('CSV harus menggunakan UTF-8.') from exc
        records=list(csv.DictReader(io.StringIO(content)))
    elif name.endswith('.xlsx'):
        df=pd.read_excel(io.BytesIO(contents),dtype=str,keep_default_na=False)
        records=df.to_dict('records')
    else: raise ValueError('Unggah CSV atau XLSX.')
    if not records: raise ValueError('File kosong.')
    missing=set(FIELDS)-set(records[0]);
    if missing: raise ValueError('Kolom wajib tidak ditemukan: '+', '.join(sorted(missing)))
    if len(records)>3000: raise ValueError('Maksimal 3000 baris per impor.')
    return [{k:str(v).strip() if v is not None else '' for k,v in r.items()} for r in records]

def validate_row(r):
    errors=[]
    def err(c): errors.append(c)
    if not r['assessment_id'] or len(r['assessment_id'])>30:err('assessment_id tidak valid')
    if r['input_source'] not in ('GOOGLE_FORM','MANUAL'):err('input_source harus GOOGLE_FORM/MANUAL')
    if not r['resident_code'] or len(r['resident_code'])>25:err('resident_code tidak valid')
    if not r['resident_name'] or len(r['resident_name'])>150:err('resident_name kosong/tidak valid')
    try:
        room=int(r['room_id'])
        if room<1 or room>999:err('room_id tidak valid')
    except ValueError:err('room_id bukan angka')
    try:
        days=int(r['stay_days_7d']); interaction=int(r['close_interactions_7d'])
        if not 0<=days<=7 or not 0<=interaction<=1000:err('hari tinggal/interaksi di luar batas')
    except ValueError:err('hari tinggal/interaksi harus bilangan bulat')
    if r['varicella_history'] not in ('YA','TIDAK','TIDAK_TAHU'):err('riwayat cacar air tidak valid')
    for name in ('history_verified','vaccine_verified'):
        if r[name] not in ('YA','TIDAK'):err(name+' harus YA/TIDAK')
    if r['vaccine_doses_documented']:
        if r['vaccine_doses_documented'] not in ('0','1','2'):err('vaksin harus 0, 1, 2, atau kosong')
    if r['last_varicella_year']:
        try:
            if not 1900<=int(r['last_varicella_year'])<=date.today().year:err('tahun cacar air tidak valid')
        except ValueError:err('tahun cacar air bukan angka')
    if r['contact_case_21d'] not in ('YA','YA_DILAPORKAN','TIDAK_ADA_DIKETAHUI','TIDAK_YAKIN'):err('contact_case_21d tidak valid')
    if r['contact_date']:
        try:date.fromisoformat(r['contact_date'])
        except ValueError:err('contact_date wajib YYYY-MM-DD')
    if r['contact_type'] and r['contact_type'] not in ('SATU_RUANGAN','TATAP_MUKA','KONTAK_LANGSUNG','LAINNYA'):err('contact_type tidak valid')
    if r['consent_status']!='SETUJU':err('persetujuan belum diberikan')
    try: datetime.fromisoformat(r['submitted_at'])
    except ValueError:err('submitted_at wajib YYYY-MM-DD HH:MM')
    try:datetime.strptime(r['period'],'%Y-%m')
    except ValueError:err('period wajib YYYY-MM')
    return errors

def cluster_data(rows):
    """Rows have ready aggregated features. Returns raw clusters + descriptive priorities only."""
    if len(rows)<4:raise ValueError('Dibutuhkan minimal empat kamar siap analisis untuk K=3.')
    data=[]
    for r in rows:
        p=float(r['verified_immunity_rate']); i=float(r['avg_close_interactions_7d']); n=float(r['active_occupants'])
        if not (0<=p<=1 and i>=0 and n>=1):raise ValueError('Fitur kamar tidak valid.')
        data.append([p,i,n])
    import numpy as np
    X=np.asarray(data,dtype=float)
    scaled=StandardScaler().fit_transform(X)
    if np.unique(scaled,axis=0).shape[0]<3:raise ValueError('Kurang dari tiga profil kamar unik untuk K=3.')
    labels=KMeans(n_clusters=3,n_init=20,random_state=42).fit_predict(scaled)
    distinct=len(set(labels))
    score=float(silhouette_score(scaled, labels)) if 1<distinct<len(rows) else None
    centers=[]
    for c in range(3):
        group=X[labels==c]
        centers.append({'cluster_number':c,'rooms':int(len(group)),'verified_immunity_rate':round(float(group[:,0].mean()),4) if len(group) else None,'avg_close_interactions_7d':round(float(group[:,1].mean()),2) if len(group) else None,'active_occupants':round(float(group[:,2].mean()),2) if len(group) else None})
    # For convenience only: rank relative inspection priority by cohort indicators; NOT infection likelihood.
    scoremap={c['cluster_number']:(1-c['verified_immunity_rate'])+c['avg_close_interactions_7d']/max(1,max(x['avg_close_interactions_7d'] for x in centers))+c['active_occupants']/max(1,max(x['active_occupants'] for x in centers)) for c in centers}
    order=sorted(scoremap,key=lambda k:scoremap[k]); priority={order[0]:'RENDAH',order[1]:'SEDANG',order[2]:'TINGGI'}
    for c in centers:c['relative_check_priority']=priority[c['cluster_number']]
    return {'labels':[int(x) for x in labels], 'centroids':centers,'silhouette':round(score,5) if score is not None else None,'feature_names':['verified_immunity_rate','avg_close_interactions_7d','active_occupants'],'interpretation_note':'Prioritas pemeriksaan relatif dari indikator dalam sampel; bukan tingkat risiko medis atau probabilitas infeksi.'}
