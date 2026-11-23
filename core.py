"""Analisis eksploratif karakteristik kamar, bukan prediksi risiko medis."""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score, adjusted_rand_score

FEATURES = ['occupant_count','interaction_frequency','shared_facility_frequency','ventilation_score']
HALL_ROOMS = {
 'Simply': set(range(101,117)),
 'Hip Hip': set(range(117,133)),
 'Hotred': set(range(217,232)),
 'Beepee': set(range(201,217)),
}
REQUIRED = ['room_id','hall']+FEATURES

class ValidationError(ValueError): pass

def validate(frame):
    if not isinstance(frame,pd.DataFrame) or frame.empty: raise ValidationError('Dataset kosong.')
    d=frame.copy()
    missing=[c for c in REQUIRED if c not in d.columns]
    if missing: raise ValidationError('Kolom belum lengkap: '+', '.join(missing))
    try:
        d['room_id']=pd.to_numeric(d.room_id,errors='raise')
        for c in FEATURES:d[c]=pd.to_numeric(d[c],errors='raise')
    except (ValueError,TypeError) as e: raise ValidationError('Kolom numerik tidak valid.') from e
    if d[REQUIRED].isna().any().any():raise ValidationError('Kolom wajib berisi nilai kosong.')
    if d.room_id.duplicated().any():raise ValidationError('room_id duplikat.')
    if not np.isfinite(d[FEATURES].to_numpy(dtype=float)).all():raise ValidationError('Terdapat nilai numerik tak hingga.')
    for room,hall in zip(d.room_id,d.hall):
        if hall not in HALL_ROOMS or room not in HALL_ROOMS[hall]:
            raise ValidationError(f'Kamar {room} tidak sesuai hall {hall}.')
    d['room_id'] = d.room_id.astype(int)
    if (d[FEATURES]<0).any().any():raise ValidationError('Fitur tidak boleh negatif.')
    if (d.occupant_count<1).any() or not (d.occupant_count == d.occupant_count.round()).all():
        raise ValidationError('Jumlah penghuni harus bilangan bulat positif.')
    if not d.ventilation_score.isin([0,1,2]).all():raise ValidationError('ventilation_score harus 0, 1, atau 2.')
    if len(d)<4:raise ValidationError('Minimal empat kamar diperlukan untuk contoh clustering.')
    return d

def cluster(frame,k=2,seed=42):
    d=validate(frame)
    if not 2<=k<len(d):raise ValidationError('K harus antara 2 dan jumlah kamar - 1.')
    x=d[FEATURES].to_numpy(dtype=float)
    scaler=StandardScaler()
    z=scaler.fit_transform(x)
    if np.unique(z,axis=0).shape[0]<k:raise ValidationError('Jumlah pola unik kurang dari K.')
    model=KMeans(n_clusters=k,n_init=20,random_state=seed)
    label=model.fit_predict(z)
    actual=len(set(label))
    if actual<2 or actual>=len(d):raise ValidationError('Jumlah cluster terbentuk tidak memungkinkan evaluasi.')
    d=d.copy();d['cluster']=[f'Cluster {c+1}' for c in label]
    score=float(silhouette_score(z,label))
    centers=pd.DataFrame(scaler.inverse_transform(model.cluster_centers_),columns=FEATURES)
    return d,score,model,scaler,centers

def compare_k(frame,max_k=5):
    d=validate(frame)
    result=[]
    for k in range(2,min(max_k,len(d)-1)+1):
        try:
            _,score,_,_,_=cluster(d,k)
            result.append({'K':k,'Silhouette Score':round(score,4)})
        except ValidationError:continue
    return pd.DataFrame(result)

def stability(frame,k=2,tries=20):
    d=validate(frame)
    z=StandardScaler().fit_transform(d[FEATURES].to_numpy(dtype=float))
    ref=KMeans(n_clusters=k,random_state=42,n_init=20).fit_predict(z)
    scores=[]
    for seed in range(tries):
        lab=KMeans(n_clusters=k,random_state=seed,n_init=20).fit_predict(z)
        scores.append(adjusted_rand_score(ref,lab))
    return min(scores),float(np.mean(scores)),max(scores)

def recommendations(cluster_summary,overall):
    """Saran administratif berdasar perbedaan relatif; bukan penilaian medis."""
    rec=[]
    for _,r in cluster_summary.iterrows():
        key=str(r['cluster'])
        if r['interaction_frequency']>overall['interaction_frequency']:
            rec.append((key,'Interaksi antarkamar relatif lebih tinggi','Tinjau aktivitas berkumpul dan perkuat edukasi pencegahan cacar air.'))
        if r['shared_facility_frequency']>overall['shared_facility_frequency']:
            rec.append((key,'Penggunaan fasilitas relatif lebih tinggi','Tinjau penggunaan ruang bersama dan akses informasi pencegahan.'))
        if r['ventilation_score']<overall['ventilation_score']:
            rec.append((key,'Indikator bukaan udara relatif lebih rendah','Minta pemeriksaan ventilasi kamar oleh pengelola/petugas teknis.'))
        if r['occupant_count']>overall['occupant_count']:
            rec.append((key,'Penghuni relatif lebih banyak','Tinjau kapasitas hunian dan jarak antar-tempat tidur.'))
        if not any(x[0]==key for x in rec):
            rec.append((key,'Tidak ada indikator relatif menonjol','Pertahankan edukasi pencegahan rutin.'))
    return pd.DataFrame(rec,columns=['cluster','temuan','rencana_tindakan'])
