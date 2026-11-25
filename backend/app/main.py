"""Edelweiss prevention API: existing MySQL schema, authenticated endpoints."""
import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.database import get_engine
from app.auth import router as auth_router, current_session
from app.routes import router as app_router

app = FastAPI(title='Edelweiss Prevention Intelligence API', version='1.0.0')
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in os.getenv('CORS_ORIGINS','http://127.0.0.1:5173,http://localhost:5173').split(',') if x.strip()],allow_credentials=True,allow_methods=['GET','POST','PUT','PATCH'],allow_headers=['Content-Type','X-CSRF-Token'])
app.include_router(auth_router)
app.include_router(app_router)

@app.get('/api/health')
def health():
    try:
        with get_engine().connect() as c: c.execute(text('SELECT 1'))
        return {'api':'online','database':'connected'}
    except SQLAlchemyError as exc: raise HTTPException(503,'Koneksi database gagal. Periksa .env dan MySQL.') from exc

@app.get('/api/dashboard/summary')
def summary(user=Depends(current_session)):
    with get_engine().connect() as c:
        data=c.execute(text('''SELECT (SELECT COUNT(*) FROM halls) total_halls,
        (SELECT COUNT(*) FROM rooms) total_rooms,
        (SELECT COUNT(*) FROM residents) total_residents,
        (SELECT COUNT(*) FROM assessment_responses) total_responses,
        (SELECT COUNT(*) FROM room_feature_snapshots) total_room_snapshots,
        (SELECT COUNT(*) FROM clustering_runs) total_clustering_runs,
        (SELECT COUNT(*) FROM residents WHERE data_type='SINTETIS') synthetic_residents,
        (SELECT COUNT(*) FROM exposure_reports WHERE follow_up_status <> 'SELESAI') pending_exposure_reports,
        (SELECT COUNT(*) FROM follow_up_actions WHERE action_status NOT IN ('SELESAI','TIDAK_BERLAKU')) pending_actions''')).mappings().one()
    return {**dict(data),'data_notice':'Data awal adalah simulasi, bukan data kesehatan nyata.'}
