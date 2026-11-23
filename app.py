"""Edelweiss Prevention Intelligence — light, prevention-first Streamlit dashboard."""
from pathlib import Path
import io
import pandas as pd
from zipfile import BadZipFile
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from core import FEATURES, HALL_ROOMS, ValidationError, validate, cluster, compare_k, stability
from prevention import action_plan, dataset_fingerprint, read_actions, save_action, join_actions

ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title='Edelweiss Prevention Intelligence',page_icon='🌼',layout='wide',initial_sidebar_state='expanded')

CSS="""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], [data-testid="stApp"] {font-family:'DM Sans',Arial,sans-serif;}
[data-testid="stApp"] {background: #F8F9FB; color:#282B30;}
[data-testid="stHeader"] {background:rgba(248,249,251,.9);}
[data-testid="stSidebar"] {background: #fff; border-right:1px solid #EAEBEF;}
[data-testid="stSidebar"] > div:first-child {padding-top:24px;}
.block-container {max-width:1450px; padding: 2rem 2.8rem 3.5rem 2.8rem;}
h1,h2,h3 {letter-spacing:-.035em; color:#242528;}
h1 {font-size:2.05rem !important;font-weight:800 !important;}
h2 {font-size:1.34rem !important;font-weight:750 !important;}
h3 {font-size:1.12rem !important;font-weight:700 !important;}
p,li {line-height:1.55;}
div[data-testid="stMetric"] {background:#fff; border:1px solid #E9EAED; border-radius:15px; padding:19px 22px 18px; box-shadow:0 3px 13px rgba(38,40,45,.025);}
div[data-testid="stMetricLabel"] {color:#797D85; font-size:.9rem;}
div[data-testid="stMetricValue"] {font-size:2rem; font-weight:800; color:#202226;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-color:#ECEEF1!important;border-radius:16px!important;background:#fff;}
.stButton>button[kind="primary"], button[data-testid="stBaseButton-primary"] {background:#F48950; border:0;border-radius:10px;color:white;font-weight:700;}
.stButton>button[kind="primary"]:hover {background:#E5763F;color:#fff;}
.stButton>button {border-radius:10px;}
[data-testid="stAlert"] {border-radius:12px;}
[data-testid="stDataFrame"] {border-radius:10px;overflow:hidden;}
[data-testid="stSidebar"] .stRadio [role="radiogroup"] label {padding:7px 0;}
.hero {background:white; border:1px solid #ECEEF1;border-radius:16px;padding:22px 25px;margin:0 0 18px;}
.eyebrow {color:#E57F49;text-transform:uppercase;letter-spacing:.11em;font-weight:800;font-size:11px;margin:0 0 7px;}
.hero-title {font-weight:800;color:#222;letter-spacing:-.03em;font-size:27px;margin:0 0 5px;}
.hero-subtitle {color:#7C8089;font-size:14px;margin:0;}
.peach-banner {background:#FFF0E6;color:#9E5229;padding:12px 16px;border-radius:12px;border:1px solid #F6D9C9;font-size:13px;font-weight:650;margin:10px 0 22px;}
.soft-note {background:#F5F6F8;border:1px solid #E6E8EC;border-radius:12px;padding:12px 16px;color:#777C85;font-size:13px;margin-top:14px;}
.sidebar-brand {padding:6px 0 12px;color:#242424;font-size:22px;font-weight:800;letter-spacing:-.03em;}
.sidebar-caption {font-size:12px;color:#8A8E96;padding:0 0 12px;}
.room-card {border:1px solid #EBEDF0;border-radius:12px;padding:12px;background:#fff;min-height:90px;}
.room-number {font-weight:800;font-size:20px;color:#303239;}
.room-status {color:#777D86;font-size:12px;}
.room-check {background:#FFF4ED;border:1px solid #F4DFD1;border-radius:12px;padding:17px;color:#74462F;margin:10px 0;}
.badge-label {display:inline-block;padding:4px 10px;background:#FFF0E5;border-radius:9px;color:#B75E32;font-weight:700;font-size:12px;}
.muted-caption {color:#858891;font-size:12px;}
hr {border-color:#ECEEF1 !important;}
</style>"""
st.markdown(CSS,unsafe_allow_html=True)

ALL_ROOMS=[(n,hall) for hall,rr in HALL_ROOMS.items() for n in sorted(rr)]
ROOM_PAGE = '🔎 Pemeriksaan Kamar'
NAV={'🏠 Beranda':'home','🗺️ Peta Kamar':'map',ROOM_PAGE:'room',
     '🛡️ Tindakan Pencegahan':'actions','✨ Analisis AI':'ai','📑 Laporan':'reports'}

def open_room_page(room_id=None):
    if room_id is not None:
        st.session_state.selected_room = int(room_id)
    st.session_state.page_nav = ROOM_PAGE


def describe_cluster(rooms, cluster_name):
    group_average = rooms.loc[rooms.cluster == cluster_name, FEATURES].mean().round(2)
    overall_average = rooms[FEATURES].mean().round(2)
    descriptions = []
    for feature, label, higher, lower in (
        ('occupant_count', 'penghuni', 'lebih banyak', 'lebih sedikit'),
        ('interaction_frequency', 'interaksi antarkamar', 'lebih sering', 'lebih jarang'),
        ('shared_facility_frequency', 'penggunaan fasilitas bersama', 'lebih sering', 'lebih jarang'),
        ('ventilation_score', 'skor bukaan udara', 'lebih tinggi', 'lebih rendah'),
    ):
        if group_average[feature] > overall_average[feature]:
            descriptions.append(f'{label} {higher}')
        elif group_average[feature] < overall_average[feature]:
            descriptions.append(f'{label} {lower}')
    if not descriptions:
        return 'Keempat cirinya mendekati rata-rata semua kamar yang dianalisis.'
    profile = ' dan '.join(filter(None, [', '.join(descriptions[:-1]), descriptions[-1]]))
    return f'Dibandingkan rata-rata semua kamar yang dianalisis, kelompok ini punya {profile}.'


with st.sidebar:
    st.markdown('<div class="sidebar-brand">🌼 Edelweiss</div><div class="sidebar-caption">Prevention Intelligence · Asrama</div>',unsafe_allow_html=True)
    st.markdown('---')
    page_label=st.radio('Menu',list(NAV),label_visibility='collapsed',key='page_nav')
    st.markdown('---')
    with st.expander('⚙️ Pengaturan data',expanded=False):
        source=st.radio('Sumber analisis',['Data simulasi','Unggah data asli'],key='dataset_source')
        uploaded=st.file_uploader('Pilih file CSV/Excel',type=['csv','xlsx'],key='uploaded_file') if source=='Unggah data asli' else None
        k=st.select_slider('Jumlah kelompok (K)',options=[2,3,4,5],value=2,key='cluster_k')
        st.caption('Pengaturan ini memengaruhi analisis AI; beranda tetap dapat digunakan tanpa memahami K-Means.')
    st.caption('🌼 K-Means membantu mengelompokkan kondisi kamar, bukan mendiagnosis atau memprediksi cacar air.')

if source=='Unggah data asli' and uploaded is None:
    st.info('Untuk menggunakan data asli, buka **⚙️ Pengaturan data** di panel kiri dan unggah file CSV/Excel. Kamu juga bisa memilih Data simulasi untuk melihat contoh dashboard.')
    st.stop()
try:
    if uploaded is None:
        raw=pd.read_csv(ROOT/'data'/'dummy_rooms.csv')
    else:
        raw=pd.read_excel(uploaded) if uploaded.name.lower().endswith('xlsx') else pd.read_csv(uploaded)
    df=validate(raw)
except (KeyError, ValueError, ImportError, OSError, BadZipFile) as ex:
    st.error(f'Data belum bisa dipakai: {ex}')
    st.caption('Kolom wajib: room_id, hall, occupant_count, interaction_frequency, shared_facility_frequency, ventilation_score.')
    st.stop()

signature=dataset_fingerprint(df)
source_tag='SIMULASI' if source=='Data simulasi' else 'DATA ASLI (diunggah)'
run_key=f'{signature}-k{k}'

@st.cache_data(show_spinner=False)
def load_analysis(frame_csv,k):
    d=pd.read_csv(io.StringIO(frame_csv))
    result,score,model,scaler,centers=cluster(d,k)
    ktable=compare_k(d)
    try:stead=stability(d,k,tries=12)
    except Exception:stead=None
    return result,score,model,scaler,centers,ktable,stead

try:
    analyzed,score,model,scaler,centers,ktable,stead=load_analysis(df.to_csv(index=False),k)
except (ValidationError,ValueError) as ex:
    st.error('Clustering tidak dapat diproses: '+str(ex));st.stop()

plan=action_plan(analyzed)
history=read_actions(run_key)
tracked=join_actions(plan,history)
room_plan=(plan.groupby('room_id').size().to_dict() if not plan.empty else {})
attn_rooms=len(room_plan)
complete=(tracked.status=='Selesai').sum() if not tracked.empty else 0

st.markdown('''<div class="hero"><div class="eyebrow">🌼 Dormitory Health & Prevention</div>
<div class="hero-title">Edelweiss Prevention Intelligence</div>
<div class="hero-subtitle">Membantu pengelola memahami kondisi kamar dan merencanakan pemeriksaan pencegahan cacar air.</div></div>''',unsafe_allow_html=True)
if source=='Data simulasi':
    st.markdown('<div class="peach-banner">DATA SIMULASI — angka pemeriksaan, kondisi kamar, dan rekomendasi di bawah bukan hasil survei asli asrama.</div>',unsafe_allow_html=True)
else:
    st.markdown('<div class="peach-banner">DATA UNGGAHAN — hasil perlu ditinjau pengelola dan tidak boleh dianggap sebagai diagnosis atau skor risiko medis.</div>',unsafe_allow_html=True)

page=NAV[page_label]

if page=='home':
    st.header('Ringkasan kondisi asrama')
    st.markdown("""
1. Buka **Peta Kamar** dan pilih kamar.
2. Baca apa yang perlu dicek di **Pemeriksaan Kamar**.
3. Setelah mengecek kamar, catat hasilnya di **Tindakan Pencegahan**.
""")
    a,b,c,d=st.columns(4)
    a.metric('🏘️ Total kamar asrama',63)
    b.metric('🏢 Jumlah hall',4)
    c.metric('📋 Kamar dianalisis',len(analyzed))
    d.metric('🔎 Kamar dengan catatan pemeriksaan',attn_rooms)
    st.caption('Catatan ini menunjukkan apa yang perlu dicek langsung. Catatan ini tidak menunjukkan siapa yang sakit.')
    left,right=st.columns([1.25,1],gap='medium')
    with left:
        with st.container(border=True):
            st.subheader('Kamar yang perlu diperiksa')
            if tracked.empty:
                st.success('Belum ada saran pemeriksaan tambahan dari data ini.')
            else:
                view=tracked.groupby(['room_id','hall'],as_index=False).agg(jumlah_pemeriksaan=('action_id','size'))
                view=view.sort_values(['jumlah_pemeriksaan','room_id'],ascending=[False,True]).head(8)
                view=view.rename(columns={'room_id':'Kamar','hall':'Hall','jumlah_pemeriksaan':'Catatan pemeriksaan'})
                st.dataframe(view,use_container_width=True,hide_index=True)
            st.button('Lihat pemeriksaan kamar', key='goto_room', on_click=open_room_page)
    with right:
        with st.container(border=True):
            st.subheader('Ringkasan tindakan')
            counts=tracked.status.value_counts() if not tracked.empty else pd.Series(dtype=int)
            fig=go.Figure(data=[go.Pie(labels=['Belum ditinjau','Dalam proses','Selesai','Tidak berlaku'],
                    values=[int(counts.get(v,0)) for v in ['Belum ditinjau','Dalam proses','Selesai','Tidak berlaku']],
                    hole=.66,marker_colors=['#FAB384','#F4D39A','#9ECAAD','#CDD0D7'],textinfo='percent')]) if counts.sum()>0 else None
            if fig is not None:
                fig.update_layout(showlegend=True,height=260,margin=dict(l=2,r=2,t=7,b=2),paper_bgcolor='rgba(0,0,0,0)',font=dict(color='#4B5158'),legend=dict(orientation='h',y=-.05))
                st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})
            else:st.info('Belum ada tindakan tercatat.')
            st.caption(f'{complete} dari {len(tracked)} tugas pemeriksaan ditandai selesai.')
    left,right=st.columns(2,gap='medium')
    with left:
        with st.container(border=True):
            st.subheader('Mengapa asrama bersih masih bisa ada cacar air?')
            st.write('Cacar air menular antarmanusia, termasuk melalui partikel infeksius di udara. Pembersihan rutin tetap penting, tetapi tidak menggantikan pencegahan paparan, penanganan kasus, dan perhatian pada ventilasi.')
            st.caption('K-Means menampilkan kemiripan karakteristik kamar; penyebab kasus historis tidak dapat dipastikan dari data simulasi ini.')
    with right:
        with st.container(border=True):
            st.subheader('Periksa kamar dengan cepat')
            home_room=st.selectbox('Pilih nomor kamar',sorted(analyzed.room_id.astype(int).tolist()),key='home_room')
            items=plan[plan.room_id==home_room]
            if items.empty:st.success('Belum ada saran pemeriksaan tambahan untuk kamar ini. Tetap lakukan pemeriksaan rutin.')
            else:
                st.markdown(f'<span class="badge-label">{len(items)} catatan pemeriksaan</span>',unsafe_allow_html=True)
                st.write(' • '.join(items.pemeriksaan.tolist()))
            st.button('Buka detail kamar', key='home_goto_room',
                      on_click=open_room_page, args=(home_room,))
    st.markdown('<div class="soft-note">Catatan: terdapat riwayat cacar air di asrama, tetapi rincian lokasi dan penghuni tidak disebarkan melalui dashboard umum. Jika ada dugaan kasus baru, segera koordinasikan dengan petugas kesehatan tanpa menunggu hasil K-Means.</div>',unsafe_allow_html=True)

elif page=='map':
    st.header('Peta kamar asrama')
    st.write('Pilih hall, lalu klik **Lihat kamar**. Label **Belum dianalisis** berarti data kamar belum tersedia.')
    chosen=st.selectbox('Hall',['Semua hall','Simply','Hip Hip','Hotred','Beepee'],key='map_hall')
    analyzed_rooms = set(analyzed.room_id)
    for hall,rooms in HALL_ROOMS.items():
        if chosen!='Semua hall' and chosen!=hall:continue
        st.subheader(f'{hall} · {len(rooms)} kamar')
        rlist=sorted(rooms)
        for start in range(0,len(rlist),4):
            columns=st.columns(4)
            for col,n in zip(columns,rlist[start:start+4]):
                with col:
                    with st.container(border=True):
                        st.markdown(f'<div class="room-number">{n}</div>',unsafe_allow_html=True)
                        status=('Perlu diperiksa' if room_plan.get(n,0) else 'Tidak ada catatan khusus') if n in analyzed_rooms else 'Belum dianalisis'
                        st.caption(status)
                        st.button('Lihat kamar', key=f'map_{n}', use_container_width=True,
                                  on_click=open_room_page, args=(n,))

elif page=='room':
    st.header('Pemeriksaan kamar')
    st.write('Pilih nomor kamar untuk melihat apa yang perlu dicek, alasannya, dan tindakan yang disarankan.')
    all_ids=sorted([x for x,h in ALL_ROOMS])
    sel=st.session_state.get('selected_room',all_ids[0])
    if sel not in all_ids:sel=all_ids[0]
    if 'room_select' not in st.session_state:
        st.session_state.room_select = sel
    room=st.selectbox('Nomor kamar',all_ids,key='room_select')
    st.session_state.selected_room=room
    hall=next(h for n,h in ALL_ROOMS if n==room)
    st.caption('Hall: '+hall)
    matched=analyzed[analyzed.room_id==room]
    if matched.empty:
        st.info('Data kamar ini belum tersedia. Cek kondisi kamar langsung bila diperlukan.')
    else:
        row=matched.iloc[0]
        c1,c2,c3,c4=st.columns(4)
        c1.metric('Penghuni',int(row.occupant_count))
        c2.metric('Interaksi antarkamar / minggu',f'{row.interaction_frequency:g}')
        c3.metric('Penggunaan fasilitas bersama / minggu',f'{row.shared_facility_frequency:g}')
        c4.metric('Skor bukaan udara',int(row.ventilation_score))
        st.info(f'**{row.cluster}** — {describe_cluster(analyzed, row.cluster)}')
        items=tracked[tracked.room_id==room]
        st.subheader('Apa yang perlu dicek?')
        if items.empty:
            st.info('Data kamar ini tidak memicu saran tambahan. Tetap lakukan pemeriksaan rutin.')
        else:
            for _,r in items.iterrows():
                with st.container(border=True):
                    st.markdown('**'+r.pemeriksaan+'**')
                    st.write(r.alasan)
                    st.write('**Saran:** '+r.tindakan)
                    st.caption('Status tindak lanjut: '+r.status)
        st.divider()
        with st.expander('Coba simulasi pengelompokan kamar (opsional)'):
            cc1,cc2=st.columns(2)
            with cc1:
                occ=st.number_input('Jumlah penghuni simulasi',1,max(12,int(row.occupant_count)),int(row.occupant_count),1)
                inter=st.number_input('Interaksi / 7 hari',0.,value=float(row.interaction_frequency),step=.5)
            with cc2:
                fac=st.number_input('Fasilitas / 7 hari',0.,value=float(row.shared_facility_frequency),step=.5)
                vent=st.selectbox('Bukaan udara',[0,1,2],index=int(row.ventilation_score))
            if st.button('Lihat hasil simulasi'):
                transformed=scaler.transform([[occ,inter,fac,vent]])
                prediction=int(model.predict(transformed)[0])+1
                if row.cluster == f'Cluster {prediction}':
                    st.info(f'Hasil simulasi: kamar tetap paling mirip dengan Kelompok {prediction}.')
                else:
                    initial_group = row.cluster.replace('Cluster', 'Kelompok')
                    st.info(f'Hasil simulasi: kamar berpindah dari {initial_group} ke Kelompok {prediction} karena angka baru lebih mirip dengan kelompok tersebut.')

elif page=='actions':
    st.header('Tindakan pencegahan')
    st.write('Buka tugas untuk kamar yang kamu tangani. Pilih status, tambahkan catatan bila perlu, lalu klik **Simpan tindak lanjut**.')
    if tracked.empty:
        st.success('Tidak ada tugas dari aturan skrining pada dataset ini.')
    else:
        halls=['Semua hall']+sorted(df.hall.unique())
        col1,col2=st.columns(2)
        active_hall=col1.selectbox('Filter hall',halls)
        stat_options=['Semua status','Belum ditinjau','Dalam proses','Selesai','Tidak berlaku']
        active_status=col2.selectbox('Filter status',stat_options)
        view=tracked if active_hall=='Semua hall' else tracked[tracked.hall==active_hall]
        if active_status!='Semua status':view=view[view.status==active_status]
        st.caption(f'{len(view)} tugas ditampilkan')
        for _,r in view.sort_values(['room_id','action_id']).iterrows():
            key=f'{run_key}-{int(r.room_id)}-{r.action_id}'
            with st.expander(f'Kamar {int(r.room_id)} · {r.pemeriksaan} · {r.status}'):
                st.write('**Alasan:** '+r.alasan)
                st.write('**Tindakan yang disarankan:** '+r.tindakan)
                with st.form(f'action_form_{key}'):
                    statuses=['Belum ditinjau','Dalam proses','Selesai','Tidak berlaku']
                    newstatus=st.selectbox('Status tugas',statuses,index=statuses.index(r.status))
                    note=st.text_area('Catatan pengelola (tanpa identitas/riwayat medis penghuni)',value=r.note,max_chars=500,height=80)
                    if st.form_submit_button('Simpan tindak lanjut',type='primary'):
                        save_action(run_key,int(r.room_id),r.action_id,newstatus,note)
                        st.success('Status disimpan di komputer ini.');st.rerun()
    st.info('Jika ada penghuni yang diduga terkena cacar air, langsung hubungi petugas kesehatan.')

elif page=='ai':
    st.header('Analisis AI · K-Means')
    st.caption('K-Means mengelompokkan kamar berdasarkan kemiripan empat karakteristik yang tercatat.')
    a,b,c=st.columns(3)
    a.metric('Jumlah kelompok (K)',k)
    b.metric('Kamar diproses',len(analyzed))
    c.metric('Silhouette Score',f'{score:.3f}')
    if score<.3:st.warning('Pemisahan kelompok lemah. Hasil bersifat eksploratif; jangan digunakan sebagai peringkat risiko penyakit.')
    left,right=st.columns(2)
    with left:
        st.subheader('Perbandingan K')
        if not ktable.empty:
            fig=px.line(ktable,x='K',y='Silhouette Score',markers=True,color_discrete_sequence=['#F48950'])
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',height=300,margin=dict(l=2,r=2,t=16,b=6))
            st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})
    with right:
        st.subheader('Jumlah kamar per kelompok')
        ct=analyzed.cluster.value_counts().reset_index();ct.columns=['Kelompok','Jumlah kamar']
        fig=px.bar(ct,x='Kelompok',y='Jumlah kamar',color='Kelompok',color_discrete_sequence=['#F48950','#F7BA8A','#B7CFBE','#8FB4C9','#C3BAD5'])
        fig.update_layout(paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',height=300,showlegend=False,margin=dict(l=2,r=2,t=16,b=6))
        st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})
    st.subheader('Apa yang membedakan kelompok?')
    summary=analyzed.groupby('cluster',as_index=False)[FEATURES].mean().round(2)
    for cluster_name in summary.cluster:
        st.write(f'**{cluster_name}** — {describe_cluster(analyzed, cluster_name)}')
    st.dataframe(summary.rename(columns={'cluster':'Kelompok','occupant_count':'Rata-rata penghuni','interaction_frequency':'Interaksi / 7 hari','shared_facility_frequency':'Fasilitas / 7 hari','ventilation_score':'Bukaan udara'}),use_container_width=True,hide_index=True)
    if stead is not None:st.caption('Konsistensi inisialisasi ARI (min / rerata / maks): '+' / '.join(f'{v:.3f}' for v in stead))
    st.subheader('Data yang digunakan')
    st.dataframe(analyzed,use_container_width=True,hide_index=True)
    st.caption('K-Means mengelompokkan kemiripan karakteristik kamar, bukan menghitung penyebab kasus atau probabilitas tertular.')

elif page=='reports':
    st.header('Laporan dan unduh data')
    st.write('Unduh hasil untuk laporan proyek. Data kasus historis sensitif tidak ikut diekspor.')
    export=analyzed.copy()
    export['sumber']=source_tag
    export['K']=k
    export['silhouette_score']=round(score,4)
    export['catatan']='Karakteristik kamar; bukan penilaian risiko medis'
    st.download_button('⬇️ Unduh hasil K-Means (CSV)',export.to_csv(index=False).encode('utf-8-sig'),'hasil_kmeans_edelweiss.csv','text/csv',type='primary')
    exported=tracked.copy()
    if not exported.empty:
        st.download_button('⬇️ Unduh daftar pemeriksaan & status (CSV)',exported.to_csv(index=False).encode('utf-8-sig'),'tindakan_pencegahan_edelweiss.csv','text/csv')
    st.divider()
    st.subheader('Ringkasan metode')
    st.write(f'Data: {source_tag} | Kamar dianalisis: {len(analyzed)} | K-Means: K={k} | Silhouette Score: {score:.4f}.')
    st.caption('Aturan skrining menggunakan ventilation_score = 0 serta nilai interaksi, fasilitas, dan penghuni di atas persentil 75 masing-masing fitur. Aturan ini dibuat sebagai contoh administratif, belum divalidasi sebagai ukuran risiko medis.')
    st.caption('Data asli sebaiknya digunakan hanya setelah izin, kualitas, dan periode pencatatan diverifikasi.')
