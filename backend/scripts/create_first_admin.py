"""One-time interactive creation of admin; doesn't touch existing resident/room data."""
import getpass
import sys
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.database import get_engine
from app.security import hash_password


def main():
    print("=== Buat Administrator Pertama - Edelweiss ===")
    username=input("Username admin: ").strip()
    email=input("Email admin: ").strip()
    display_name=input("Nama tampilan: ").strip()
    if not username or len(username)>80 or not email or "@" not in email or not display_name:
        raise SystemExit("Username, email, dan nama wajib valid.")
    password=getpass.getpass("Password admin (minimal 12 karakter): ")
    confirm=getpass.getpass("Ulangi password: ")
    if password!=confirm:
        raise SystemExit("Password tidak sama. Tidak ada akun dibuat.")
    hashed=hash_password(password)
    with get_engine().begin() as conn:
        admin_count=conn.execute(text("SELECT COUNT(*) FROM users u JOIN roles r ON u.role_id=r.role_id WHERE r.role_name='ADMIN'")).scalar_one()
        if admin_count:
            raise SystemExit("Sudah ada admin. Skrip ini hanya untuk admin pertama.")
        role_id=conn.execute(text("SELECT role_id FROM roles WHERE role_name='ADMIN'")).scalar_one_or_none()
        if role_id is None:
            raise SystemExit("Role ADMIN tidak ditemukan. Periksa seed database.")
        conn.execute(text("""
            INSERT INTO users(role_id,username,email,display_name,password_hash,is_active)
            VALUES(:role_id,:username,:email,:display_name,:password_hash,1)
        """),{"role_id":role_id,"username":username,"email":email,
             "display_name":display_name,"password_hash":hashed})
    print("Admin pertama berhasil dibuat. Password tidak ditampilkan/disimpan sebagai teks biasa.")

if __name__=="__main__":
    main()
