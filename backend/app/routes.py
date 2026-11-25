"""Authenticated, role-protected CRUD/import/analysis for existing MySQL schema."""
import json, uuid
from collections import defaultdict
from datetime import date,datetime,timedelta
from io import BytesIO
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
from app.auth import current_session,require_csrf,require_roles
from app.database import get_engine
from app.logic import decode_file,validate_row,cluster_data

router=APIRouter(prefix='/api',tags=['Edelweiss'])
STAFF=('ADMIN','PETUGAS_ASRAMA','PETUGAS_KESEHATAN')
HEALTH=('ADMIN','PETUGAS_KESEHATAN')

def fetch_all(query,params=None):
    with get_engine().connect() as c:return [dict(x) for x in c.execute(text(query),params or {}).mappings().all()]

def fetch_one(query,params=None):
    with get_engine().connect() as c:
        row=c.execute(text(query),params or {}).mappings().first()
        return dict(row) if row else None

def audit(c,user,action,entity,key):
    c.execute(text('INSERT INTO audit_logs(user_id,action_type,entity_name,entity_key) VALUES(:u,:a,:e,:k)'),{'u':user,'a':action,'e':entity,'k':str(key)})

@router.get('/halls')
def halls(user=Depends(current_session)):
    return fetch_all('SELECT h.hall_id,h.hall_name,COUNT(r.room_id) total_rooms FROM halls h LEFT JOIN rooms r ON r.hall_id=h.hall_id GROUP BY h.hall_id,h.hall_name ORDER BY h.hall_id')

@router.get('/rooms')
def rooms(hall_id:int|None=None,user=Depends(current_session)):
    return fetch_all('''SELECT r.room_id,r.capacity,r.is_active,h.hall_name,h.hall_id,COUNT(m.membership_id) active_occupants
    FROM rooms r JOIN halls h ON h.hall_id=r.hall_id LEFT JOIN room_memberships m ON m.room_id=r.room_id AND m.end_date IS NULL
    WHERE (:h IS NULL OR r.hall_id=:h) GROUP BY r.room_id,r.capacity,r.is_active,h.hall_name,h.hall_id ORDER BY r.room_id''',{'h':hall_id})

@router.get('/periods')
def periods(user=Depends(current_session)):
    return [{**r,'start_date':str(r['start_date']),'end_date':str(r['end_date'])} for r in fetch_all('SELECT period_id,period_code,start_date,end_date,status FROM assessment_periods ORDER BY period_code DESC')]

class PeriodIn(BaseModel):
    period_code:str=Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')

@router.post('/periods')
def create_period(payload:PeriodIn,user=Depends(require_csrf)):
    if user['role_name'] not in STAFF:raise HTTPException(403,'Tidak berwenang')
    start=date.fromisoformat(payload.period_code+'-01'); nextm=date(start.year+(start.month==12),start.month%12+1,1)
    try:
        with get_engine().begin() as c:
            result=c.execute(text("INSERT INTO assessment_periods(period_code,start_date,end_date,status,created_by) VALUES(:p,:s,:e,'OPEN',:u)"),{'p':payload.period_code,'s':start,'e':nextm-timedelta(days=1),'u':user['user_id']})
            audit(c,user['user_id'],'PERIOD_CREATE','assessment_periods',result.lastrowid)
        return {'period_id':result.lastrowid,'period_code':payload.period_code}
    except IntegrityError:raise HTTPException(409,'Periode tersebut sudah tersedia.')

@router.get('/residents')
def residents(room_id:int|None=None,period:str|None=None,user=Depends(current_session)):
    # Ordinary staff sees administrative identity + completion only. No personal health details.
    return fetch_all('''SELECT r.resident_id,r.resident_code,r.resident_name,m.room_id,m.start_date,m.end_date,
      CASE WHEN a.assessment_id IS NULL THEN 'BELUM_MENGISI' ELSE a.review_status END assessment_status,
      a.input_source
      FROM residents r JOIN room_memberships m ON m.resident_id=r.resident_id
      LEFT JOIN assessment_responses a ON a.resident_id=r.resident_id AND a.period_id=(SELECT period_id FROM assessment_periods WHERE period_code=:p LIMIT 1)
      WHERE (:room IS NULL OR m.room_id=:room) AND m.end_date IS NULL ORDER BY m.room_id,r.resident_name''',{'room':room_id,'p':period or '2026-11'})

@router.get('/assessment/completeness')
def completeness(period:str,user=Depends(current_session)):
    return fetch_all('''SELECT h.hall_name,rm.room_id,COUNT(DISTINCT m.resident_id) active_occupants,
      COUNT(DISTINCT CASE WHEN a.review_status='VALID' THEN a.resident_id END) valid_responses,
      COUNT(DISTINCT CASE WHEN a.review_status IS NULL THEN m.resident_id END) missing_responses
      FROM rooms rm JOIN halls h ON h.hall_id=rm.hall_id
      LEFT JOIN room_memberships m ON m.room_id=rm.room_id AND m.start_date <= (SELECT end_date FROM assessment_periods WHERE period_code=:p LIMIT 1) AND (m.end_date IS NULL OR m.end_date >= (SELECT start_date FROM assessment_periods WHERE period_code=:p LIMIT 1))
      LEFT JOIN assessment_responses a ON a.resident_id=m.resident_id AND a.period_id=(SELECT period_id FROM assessment_periods WHERE period_code=:p LIMIT 1)
      GROUP BY rm.room_id,h.hall_name ORDER BY rm.room_id''',{'p':period})

@router.get('/snapshots')
def snapshots(period:str='2026-11',user=Depends(current_session)):
    return fetch_all('''SELECT s.snapshot_id,s.room_id,h.hall_name,s.active_occupants,s.valid_responses,s.verified_immunity_count,s.verified_immunity_rate,s.avg_close_interactions_7d,s.reported_contact_count,s.analysis_readiness,s.data_type,s.data_version
    FROM room_feature_snapshots s JOIN rooms r ON r.room_id=s.room_id JOIN halls h ON h.hall_id=r.hall_id
    JOIN assessment_periods p ON p.period_id=s.period_id WHERE p.period_code=:p AND s.data_version=(SELECT MAX(z.data_version) FROM room_feature_snapshots z WHERE z.room_id=s.room_id AND z.period_id=s.period_id) ORDER BY s.room_id''',{'p':period})

class AssessmentPayload(BaseModel):
    period:str
    resident_code:str
    resident_name:str
    room_id:int
    stay_days_7d:int=Field(ge=0,le=7)
    close_interactions_7d:int=Field(ge=0,le=1000)
    varicella_history:str
    last_varicella_year:int|None=None
    history_verified:bool=False
    vaccine_doses_documented:int|None=Field(default=None,ge=0,le=2)
    vaccine_verified:bool=False
    contact_case_21d:str='TIDAK_YAKIN'
    contact_date:date|None=None
    contact_type:str|None=None
    consent_status:str='SETUJU'


def db_match(c,r,period):
    p=c.execute(text('SELECT period_id,status,start_date,end_date FROM assessment_periods WHERE period_code=:p'),{'p':period}).mappings().first()
    if not p:raise ValueError('Periode belum terdaftar.')
    if p['status']!='OPEN':raise ValueError('Periode tidak menerima pemeriksaan baru.')
    person=c.execute(text('SELECT resident_id,resident_name FROM residents WHERE resident_code=:rc'),{'rc':r['resident_code']}).mappings().first()
    if not person:raise ValueError('Kode penghuni tidak terdaftar dalam master.')
    if person['resident_name'].strip().casefold()!=r['resident_name'].strip().casefold():raise ValueError('Nama tidak sesuai master penghuni.')
    mem=c.execute(text('''SELECT membership_id FROM room_memberships WHERE resident_id=:rid AND room_id=:room AND start_date<=:end AND (end_date IS NULL OR end_date>=:start) ORDER BY start_date DESC LIMIT 1'''),{'rid':person['resident_id'],'room':int(r['room_id']),'start':p['start_date'],'end':p['end_date']}).mappings().first()
    if not mem:raise ValueError('Penghuni tidak tercatat di kamar pada periode ini.')
    already=c.execute(text('SELECT assessment_id FROM assessment_responses WHERE period_id=:p AND resident_id=:r'),{'p':p['period_id'],'r':person['resident_id']}).scalar_one_or_none()
    if already:raise ValueError('Penghuni sudah memiliki pemeriksaan untuk periode tersebut.')
    return p['period_id'],person['resident_id'],mem['membership_id']


def store_assessment(c,r,user_id,source=None,batch=None):
    period_id,resident_id,membership_id=db_match(c,r,r['period'])
    aid=r.get('assessment_id') or ('MAN-'+uuid.uuid4().hex[:22].upper())
    if source is None:source=r['input_source']
    c.execute(text('''INSERT INTO assessment_responses(assessment_id,period_id,resident_id,membership_id,submitted_at,input_source,stay_days_7d,close_interactions_7d,consent_status,review_status,import_batch_id,entered_by,data_type)
        VALUES(:aid,:p,:rid,:mid,:at,:src,:days,:inter,:consent,'VALID',:batch,:u,:type)'''),{'aid':aid,'p':period_id,'rid':resident_id,'mid':membership_id,'at':datetime.fromisoformat(r['submitted_at']),'src':source,'days':int(r['stay_days_7d']),'inter':int(r['close_interactions_7d']),'consent':r['consent_status'],'batch':batch,'u':user_id,'type':'SINTETIS' if r['resident_code'].startswith('EDW-D') else 'NYATA'})
    # Fresh self-reports are NEVER automatically treated as verified medical evidence.
    status='BELUM_TERVERIFIKASI'
    c.execute(text('''INSERT INTO immunity_records(assessment_id,varicella_history,last_varicella_year,history_verified,vaccine_doses_documented,vaccine_verified,immunity_evidence_status)
      VALUES(:a,:h,:y,:hv,:d,:vv,:status)'''),{'a':aid,'h':r['varicella_history'],'y':int(r['last_varicella_year']) if r['last_varicella_year'] else None,'hv':False,'d':int(r['vaccine_doses_documented']) if r['vaccine_doses_documented'] else None,'vv':False,'status':status})
    if r['contact_case_21d'] in ('YA','YA_DILAPORKAN'):
        c.execute(text('''INSERT INTO exposure_reports(report_id,resident_id,room_id,assessment_id,report_type,report_date,contact_date,contact_type,case_status,exposure_assessment,follow_up_status,data_type)
        VALUES(:id,:rid,:room,:aid,'KONTAK_DILAPORKAN',:date,:cd,:ct,'BELUM_DIVERIFIKASI','BELUM_DINILAI','TERBUKA',:dtype)'''),{'id':'REP-'+uuid.uuid4().hex[:20].upper(),'rid':resident_id,'room':int(r['room_id']),'aid':aid,'date':datetime.fromisoformat(r['submitted_at']),'cd':r['contact_date'] or None,'ct':r['contact_type'] or None,'dtype':'SINTETIS' if r['resident_code'].startswith('EDW-D') else 'NYATA'})
    audit(c,user_id,'ASSESSMENT_ADD','assessment_responses',aid)
    return aid

@router.post('/assessment/manual')
def manual(payload:AssessmentPayload,user=Depends(require_csrf)):
    if user['role_name'] not in STAFF:raise HTTPException(403,'Akses ditolak.')
    r=payload.model_dump();r.update({'assessment_id':'MAN-'+uuid.uuid4().hex[:22].upper(),'submitted_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'input_source':'MANUAL','last_varicella_year':str(payload.last_varicella_year or ''),'history_verified':'YA' if payload.history_verified else 'TIDAK','vaccine_doses_documented':str(payload.vaccine_doses_documented) if payload.vaccine_doses_documented is not None else '','vaccine_verified':'YA' if payload.vaccine_verified else 'TIDAK','contact_date':str(payload.contact_date) if payload.contact_date else '','contact_type':payload.contact_type or ''})
    r={k:str(v) if v is not None else '' for k,v in r.items()}
    errors=validate_row(r)
    if errors:raise HTTPException(422,errors)
    try:
        with get_engine().begin() as c: aid=store_assessment(c,r,user['user_id'],source='MANUAL')
        return {'assessment_id':aid,'message':'Pemeriksaan manual tersimpan.'}
    except ValueError as exc:raise HTTPException(422,str(exc))
    except IntegrityError as exc:raise HTTPException(409,'Pemeriksaan duplikat atau tidak sesuai database.') from exc

async def parse_upload(file:UploadFile):
    try:return decode_file(await file.read(),file.filename or '')
    except ValueError as exc:raise HTTPException(422,str(exc))


def inspect_rows(rows):
    errors=[]; seen=set()
    with get_engine().connect() as c:
        for idx,r in enumerate(rows,start=2):
            row_errors=validate_row(r)
            key=(r.get('period'),r.get('resident_code'))
            if key in seen:row_errors.append('Penghuni duplikat dalam file/periode')
            seen.add(key)
            if not row_errors:
                try:db_match(c,r,r['period'])
                except ValueError as exc:row_errors.append(str(exc))
                try:
                    hall=c.execute(text('SELECT hall_name FROM halls h JOIN rooms rm ON rm.hall_id=h.hall_id WHERE rm.room_id=:room'),{'room':int(r['room_id'])}).scalar_one_or_none()
                    if not hall or hall.casefold()!=r['hall'].casefold():row_errors.append('Hall tidak sesuai nomor kamar.')
                except (ValueError,TypeError):pass
            if row_errors: errors.append({'row':idx,'resident_code':r.get('resident_code'),'errors':row_errors})
    return {'total_rows':len(rows),'valid_rows':len(rows)-len(errors),'invalid_rows':len(errors),'errors':errors[:100]}

@router.post('/imports/preview')
async def import_preview(file:UploadFile=File(...),user=Depends(require_csrf)):
    if user['role_name'] not in STAFF:raise HTTPException(403,'Akses ditolak.')
    return inspect_rows(await parse_upload(file))

@router.post('/imports/commit')
async def import_commit(file:UploadFile=File(...),user=Depends(require_csrf)):
    if user['role_name'] not in STAFF:raise HTTPException(403,'Akses ditolak.')
    rows=await parse_upload(file)
    preview=inspect_rows(rows)
    if preview['invalid_rows']:
        raise HTTPException(422,{'message':'Impor dibatalkan. Perbaiki seluruh baris terlebih dahulu.','validation':preview})
    if len({r['period'] for r in rows})!=1:raise HTTPException(422,'File harus berisi satu periode saja.')
    try:
        with get_engine().begin() as c:
            period_id=c.execute(text('SELECT period_id FROM assessment_periods WHERE period_code=:p'),{'p':rows[0]['period']}).scalar_one()
            batch=c.execute(text("""INSERT INTO import_batches(filename,period_id,uploaded_by,total_rows,valid_rows,rejected_rows,status,validation_summary)
            VALUES(:f,:p,:u,:n,:n,0,'COMMITTED',:summary)"""),{'f':(file.filename or 'import.csv')[:255],'p':period_id,'u':user['user_id'],'n':len(rows),'summary':json.dumps({'note':'Validated before commit'})}).lastrowid
            for r in rows:store_assessment(c,r,user['user_id'],batch=batch)
            audit(c,user['user_id'],'IMPORT_COMMIT','import_batches',batch)
        return {'import_batch_id':batch,'imported':len(rows),'message':'Seluruh baris berhasil diimpor.'}
    except (IntegrityError,ValueError) as exc:raise HTTPException(409,'Impor tidak tersimpan. Ada perubahan data/duplikasi; jalankan preview lagi.') from exc

@router.post('/snapshots/rebuild')
def rebuild_snapshots(period:str,user=Depends(require_csrf)):
    if user['role_name'] not in STAFF:raise HTTPException(403,'Akses ditolak.')
    # Compute from all active memberships at period end; require full valid responses to be "SIAP".
    with get_engine().begin() as c:
        p=c.execute(text('SELECT period_id,start_date,end_date FROM assessment_periods WHERE period_code=:p'),{'p':period}).mappings().first()
        if not p:raise HTTPException(404,'Periode tidak ada.')
        rooms=c.execute(text('SELECT room_id FROM rooms ORDER BY room_id')).scalars().all()
        updated=0
        for room in rooms:
            members=c.execute(text('''SELECT resident_id FROM room_memberships WHERE room_id=:r AND start_date<=:end AND (end_date IS NULL OR end_date>=:end)'''),{'r':room,'end':p['end_date']}).scalars().all()
            active=len(members)
            aggregate=c.execute(text('''SELECT COUNT(*) valid_count,COALESCE(SUM(CASE WHEN i.immunity_evidence_status='TERVERIFIKASI' THEN 1 ELSE 0 END),0) immune,
            AVG(a.close_interactions_7d) interactions,COALESCE(SUM(CASE WHEN e.report_id IS NOT NULL THEN 1 ELSE 0 END),0) contact_count
            FROM assessment_responses a JOIN room_memberships m ON m.membership_id=a.membership_id
            LEFT JOIN immunity_records i ON i.assessment_id=a.assessment_id
            LEFT JOIN exposure_reports e ON e.assessment_id=a.assessment_id AND e.report_type='KONTAK_DILAPORKAN'
            WHERE a.period_id=:p AND m.room_id=:r AND a.review_status='VALID' AND a.consent_status='SETUJU'
            AND m.start_date<=:end AND (m.end_date IS NULL OR m.end_date>=:end)'''),{'p':p['period_id'],'r':room,'end':p['end_date']}).mappings().one()
            valid=int(aggregate['valid_count']); immune=int(aggregate['immune']);ready='SIAP' if active>=1 and valid==active else 'BELUM_LENGKAP'
            version=c.execute(text('SELECT COALESCE(MAX(data_version),0)+1 FROM room_feature_snapshots WHERE room_id=:r AND period_id=:p'),{'r':room,'p':p['period_id']}).scalar_one()
            dtype=c.execute(text('''SELECT CASE WHEN COUNT(*)=SUM(CASE WHEN res.data_type='SINTETIS' THEN 1 ELSE 0 END) THEN 'SINTETIS' ELSE 'NYATA' END FROM room_memberships m JOIN residents res ON res.resident_id=m.resident_id WHERE m.room_id=:r AND m.start_date<=:end AND (m.end_date IS NULL OR m.end_date>=:end)'''),{'r':room,'end':p['end_date']}).scalar_one()
            c.execute(text('''INSERT INTO room_feature_snapshots(room_id,period_id,active_occupants,valid_responses,verified_immunity_count,verified_immunity_rate,immunity_not_verified_count,avg_close_interactions_7d,reported_contact_count,analysis_readiness,data_version,data_type)
            VALUES(:r,:p,:active,:valid,:immune,:rate,:unverified,:inter,:contacts,:ready,:version,:dtype)'''),{'r':room,'p':p['period_id'],'active':active,'valid':valid,'immune':immune,'rate':round(immune/active,4) if active else None,'unverified':max(0,active-immune),'inter':aggregate['interactions'],'contacts':aggregate['contact_count'],'ready':ready,'version':version,'dtype':dtype})
            updated+=1
        audit(c,user['user_id'],'SNAPSHOTS_REBUILD','assessment_periods',p['period_id'])
    return {'period':period,'snapshots_created':updated,'message':'Rekap diperbarui. Riwayat versi lama tetap tersimpan.'}

@router.post('/clustering/run')
def run_clustering(period:str,user=Depends(require_csrf)):
    if user['role_name'] not in STAFF:raise HTTPException(403,'Akses ditolak.')
    rows=fetch_all('''SELECT s.snapshot_id,s.room_id,s.verified_immunity_rate,s.avg_close_interactions_7d,s.active_occupants,s.data_type
    FROM room_feature_snapshots s JOIN assessment_periods p ON p.period_id=s.period_id
    WHERE p.period_code=:p AND s.analysis_readiness IN ('SIAP','SIAP (DEMO)')
    AND s.data_version=(SELECT MAX(x.data_version) FROM room_feature_snapshots x WHERE x.room_id=s.room_id AND x.period_id=s.period_id)
    AND s.verified_immunity_rate IS NOT NULL AND s.avg_close_interactions_7d IS NOT NULL ORDER BY s.room_id''',{'p':period})
    try:output=cluster_data(rows)
    except ValueError as exc:raise HTTPException(422,str(exc))
    with get_engine().begin() as c:
        pid=c.execute(text('SELECT period_id FROM assessment_periods WHERE period_code=:p'),{'p':period}).scalar_one_or_none()
        if not pid:raise HTTPException(404,'Periode tidak ditemukan.')
        dtype='SINTETIS' if all(r['data_type']=='SINTETIS' for r in rows) else 'NYATA'
        rid=c.execute(text('''INSERT INTO clustering_runs(period_id,k_value,algorithm,random_state,feature_config,silhouette_score,centroids,interpretation_status,created_by,data_type)
        VALUES(:p,3,'KMeans',42,:config,:sil,:cent,'PROFIL_SAJA',:u,:dtype)'''),{'p':pid,'config':json.dumps({'features':output['feature_names'],'standardized':True,'priority':'illustrative cohort ranking, not medical risk'}),'sil':output['silhouette'],'cent':json.dumps(output['centroids']),'u':user['user_id'],'dtype':dtype}).lastrowid
        for row,label in zip(rows,output['labels']):
            c.execute(text('''INSERT INTO cluster_assignments(run_id,snapshot_id,cluster_number,risk_category,interpretation_notes) VALUES(:r,:s,:c,NULL,:notes)'''),{'r':rid,'s':row['snapshot_id'],'c':label,'notes':output['interpretation_note']})
        audit(c,user['user_id'],'CLUSTERING_RUN','clustering_runs',rid)
    return {'run_id':rid,'period':period,'rooms_analysed':len(rows),**output}

@router.get('/clustering/latest')
def clustering_latest(period:str='2026-11',user=Depends(current_session)):
    run=fetch_one('''SELECT r.run_id,r.k_value,r.silhouette_score,r.centroids,r.interpretation_status,r.created_at,r.data_type
    FROM clustering_runs r JOIN assessment_periods p ON p.period_id=r.period_id WHERE p.period_code=:p ORDER BY r.run_id DESC LIMIT 1''',{'p':period})
    if not run:return {'run':None,'assignments':[]}
    ass=fetch_all('''SELECT x.cluster_number,s.room_id,h.hall_name,s.verified_immunity_rate,s.avg_close_interactions_7d,s.active_occupants
    FROM cluster_assignments x JOIN room_feature_snapshots s ON s.snapshot_id=x.snapshot_id JOIN rooms rm ON rm.room_id=s.room_id JOIN halls h ON h.hall_id=rm.hall_id WHERE x.run_id=:r ORDER BY s.room_id''',{'r':run['run_id']})
    run['created_at']=str(run['created_at'])
    if isinstance(run.get('centroids'),str):run['centroids']=json.loads(run['centroids'])
    return {'run':run,'assignments':ass,'notice':'Profil cluster dan prioritas relatif, BUKAN prediksi/diagnosis risiko medis.'}

class ActionIn(BaseModel):
    room_id:int
    period:str
    action_title:str=Field(min_length=3,max_length=200)
    action_description:str|None=None
    notes:str|None=None

class ActionPatch(BaseModel):
    action_status:str
    notes:str|None=None

@router.get('/actions')
def list_actions(period:str='2026-11',user=Depends(current_session)):
    return fetch_all('''SELECT a.action_id,a.room_id,a.action_title,a.action_description,a.action_status,a.notes,a.created_at FROM follow_up_actions a JOIN assessment_periods p ON p.period_id=a.period_id WHERE p.period_code=:p ORDER BY a.action_id DESC LIMIT 200''',{'p':period})

@router.post('/actions')
def add_action(payload:ActionIn,user=Depends(require_csrf)):
    if user['role_name'] not in STAFF:raise HTTPException(403,'Akses ditolak.')
    with get_engine().begin() as c:
        pid=c.execute(text('SELECT period_id FROM assessment_periods WHERE period_code=:p'),{'p':payload.period}).scalar_one_or_none()
        if not pid:raise HTTPException(404,'Periode belum ada.')
        rid=c.execute(text('SELECT room_id FROM rooms WHERE room_id=:r'),{'r':payload.room_id}).scalar_one_or_none()
        if not rid:raise HTTPException(404,'Kamar tidak ditemukan.')
        aid=c.execute(text('''INSERT INTO follow_up_actions(room_id,period_id,action_title,action_description,action_status,assigned_to,notes)
        VALUES(:r,:p,:title,:description,'BELUM_DITINJAU',:u,:notes)'''),{'r':rid,'p':pid,'title':payload.action_title,'description':payload.action_description,'u':user['user_id'],'notes':payload.notes}).lastrowid
        audit(c,user['user_id'],'ACTION_ADD','follow_up_actions',aid)
    return {'action_id':aid}

@router.patch('/actions/{action_id}')
def update_action(action_id:int,payload:ActionPatch,user=Depends(require_csrf)):
    if user['role_name'] not in STAFF:raise HTTPException(403,'Akses ditolak.')
    if payload.action_status not in ('BELUM_DITINJAU','DALAM_PROSES','SELESAI','TIDAK_BERLAKU'):raise HTTPException(422,'Status tidak valid.')
    with get_engine().begin() as c:
        r=c.execute(text('''UPDATE follow_up_actions SET action_status=:s,notes=:n,completed_at=CASE WHEN :s='SELESAI' THEN NOW() ELSE NULL END WHERE action_id=:id'''),{'s':payload.action_status,'n':payload.notes,'id':action_id})
        if not r.rowcount:raise HTTPException(404,'Tindakan tidak ditemukan.')
        audit(c,user['user_id'],'ACTION_UPDATE','follow_up_actions',action_id)
    return {'ok':True}

@router.get('/exposure-reports')
def exposure_reports(user=Depends(current_session)):
    if user['role_name'] not in HEALTH:raise HTTPException(403,'Laporan kesehatan hanya untuk petugas berwenang.')
    return fetch_all('''SELECT e.report_id,e.room_id,e.report_type,e.report_date,e.contact_date,e.contact_type,e.case_status,e.exposure_assessment,e.follow_up_status FROM exposure_reports e ORDER BY e.report_date DESC LIMIT 200''')

class ExposurePatch(BaseModel):
    exposure_assessment:str
    follow_up_status:str
    notes:str|None=None

@router.patch('/exposure-reports/{report_id}')
def update_exposure(report_id:str,payload:ExposurePatch,user=Depends(require_csrf)):
    if user['role_name'] not in HEALTH:raise HTTPException(403,'Khusus petugas kesehatan/administrator.')
    if payload.exposure_assessment not in ('BELUM_DINILAI','RELEVAN','TIDAK_RELEVAN','TIDAK_DAPAT_DITENTUKAN') or payload.follow_up_status not in ('TERBUKA','DALAM_PROSES','SELESAI'):raise HTTPException(422,'Status tidak valid.')
    with get_engine().begin() as c:
        updated=c.execute(text('UPDATE exposure_reports SET exposure_assessment=:a,follow_up_status=:s,notes=:n,verified_by=:u WHERE report_id=:r'),{'a':payload.exposure_assessment,'s':payload.follow_up_status,'n':payload.notes,'u':user['user_id'],'r':report_id})
        if not updated.rowcount:raise HTTPException(404,'Laporan tidak ditemukan.')
        audit(c,user['user_id'],'EXPOSURE_UPDATE','exposure_reports',report_id)
    return {'ok':True}

class ImmunityVerification(BaseModel):
    history_verified:bool=False
    vaccine_verified:bool=False

@router.get('/immunity/pending')
def pending_immunity(period:str='2026-11',user=Depends(current_session)):
    if user['role_name'] not in HEALTH:raise HTTPException(403,'Hanya petugas kesehatan/administrator.')
    return fetch_all('''SELECT a.assessment_id,res.resident_code,res.resident_name,rm.room_id,i.varicella_history,i.history_verified,i.vaccine_doses_documented,i.vaccine_verified,i.immunity_evidence_status
    FROM immunity_records i JOIN assessment_responses a ON a.assessment_id=i.assessment_id
    JOIN residents res ON res.resident_id=a.resident_id JOIN room_memberships rm ON rm.membership_id=a.membership_id
    JOIN assessment_periods p ON p.period_id=a.period_id WHERE p.period_code=:p AND i.immunity_evidence_status <> 'TERVERIFIKASI'
    ORDER BY rm.room_id,res.resident_name LIMIT 300''',{'p':period})

@router.patch('/immunity/{assessment_id}/verify')
def verify_immunity(assessment_id:str,payload:ImmunityVerification,user=Depends(require_csrf)):
    if user['role_name'] not in HEALTH:raise HTTPException(403,'Hanya petugas kesehatan/administrator.')
    with get_engine().begin() as c:
        rec=c.execute(text('SELECT varicella_history,vaccine_doses_documented FROM immunity_records WHERE assessment_id=:a'),{'a':assessment_id}).mappings().first()
        if not rec:raise HTTPException(404,'Catatan tidak ditemukan.')
        evidence=(payload.history_verified and rec['varicella_history']=='YA') or (payload.vaccine_verified and rec['vaccine_doses_documented']==2)
        c.execute(text('''UPDATE immunity_records SET history_verified=:h,vaccine_verified=:v,immunity_evidence_status=:s,verified_by=:u,verified_at=NOW() WHERE assessment_id=:a'''),{'h':payload.history_verified,'v':payload.vaccine_verified,'s':'TERVERIFIKASI' if evidence else 'BELUM_TERVERIFIKASI','u':user['user_id'],'a':assessment_id})
        audit(c,user['user_id'],'IMMUNITY_VERIFIED','immunity_records',assessment_id)
    return {'ok':True,'immunity_evidence_status':'TERVERIFIKASI' if evidence else 'BELUM_TERVERIFIKASI'}

class NewStaff(BaseModel):
    username:str=Field(min_length=3,max_length=80)
    email:str=Field(min_length=5,max_length=190)
    display_name:str=Field(min_length=2,max_length=150)
    password:str=Field(min_length=12,max_length=256)
    role_name:str

@router.get('/users')
def list_users(user=Depends(current_session)):
    if user['role_name']!='ADMIN':raise HTTPException(403,'Khusus Administrator.')
    return fetch_all('SELECT u.user_id,u.username,u.email,u.display_name,r.role_name,u.is_active FROM users u JOIN roles r ON r.role_id=u.role_id ORDER BY u.user_id')

@router.post('/users')
def add_user(payload:NewStaff,user=Depends(require_csrf)):
    if user['role_name']!='ADMIN':raise HTTPException(403,'Khusus Administrator.')
    if payload.role_name not in STAFF:raise HTTPException(422,'Peran tidak valid.')
    from app.security import hash_password
    if '@' not in payload.email:raise HTTPException(422,'Email tidak valid.')
    try:
        with get_engine().begin() as c:
            rid=c.execute(text('SELECT role_id FROM roles WHERE role_name=:r'),{'r':payload.role_name}).scalar_one()
            result=c.execute(text('''INSERT INTO users(role_id,username,email,display_name,password_hash,is_active) VALUES(:r,:u,:e,:n,:p,1)'''),{'r':rid,'u':payload.username.strip(),'e':payload.email.strip(),'n':payload.display_name.strip(),'p':hash_password(payload.password)}).lastrowid
            audit(c,user['user_id'],'USER_CREATE','users',result)
        return {'user_id':result,'message':'Akun dibuat.'}
    except IntegrityError:raise HTTPException(409,'Username atau email sudah digunakan.')

class IncidentReport(BaseModel):
    resident_code:str
    room_id:int
    report_type:str
    contact_date:date|None=None
    contact_type:str|None=None
    notes:str|None=None

@router.post('/exposure-reports')
def create_exposure(payload:IncidentReport,user=Depends(require_csrf)):
    if user['role_name'] not in HEALTH:raise HTTPException(403,'Hanya petugas kesehatan/administrator.')
    if payload.report_type not in ('KONTAK_DILAPORKAN','DUGAAN_KASUS'):raise HTTPException(422,'Jenis laporan tidak valid.')
    if payload.contact_type and payload.contact_type not in ('SATU_RUANGAN','TATAP_MUKA','KONTAK_LANGSUNG','LAINNYA'):raise HTTPException(422,'Jenis kontak tidak valid.')
    with get_engine().begin() as c:
        res=c.execute(text('''SELECT r.resident_id,r.data_type FROM residents r JOIN room_memberships m ON m.resident_id=r.resident_id WHERE r.resident_code=:code AND m.room_id=:room AND m.end_date IS NULL'''),{'code':payload.resident_code,'room':payload.room_id}).mappings().first()
        if not res:raise HTTPException(422,'Kode penghuni tidak sesuai kamar aktif.')
        report='REP-'+uuid.uuid4().hex[:20].upper()
        c.execute(text('''INSERT INTO exposure_reports(report_id,resident_id,room_id,report_type,report_date,contact_date,contact_type,notes,data_type) VALUES(:id,:rid,:room,:typ,NOW(),:date,:ct,:notes,:dtype)'''),{'id':report,'rid':res['resident_id'],'room':payload.room_id,'typ':payload.report_type,'date':payload.contact_date,'ct':payload.contact_type,'notes':payload.notes,'dtype':res['data_type']})
        audit(c,user['user_id'],'EXPOSURE_REPORT_CREATE','exposure_reports',report)
    return {'report_id':report,'message':'Laporan awal dicatat, belum terverifikasi.'}
