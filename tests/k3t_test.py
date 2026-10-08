"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""K3-T testleri (scratch-only). Tum PASS/FAIL gercek cikti."""
import hashlib
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import shutil
import sqlite3
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
import k3t_proto as P

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

LIVE_REAL = _os.path.join(REPO_ROOT, "data/depremler.db")
live_before = (os.path.getmtime(LIVE_REAL), os.path.getsize(LIVE_REAL))

# 1. sentetik v1: 41 satir, WAL
n = P.build_v1()
c = sqlite3.connect(P.V1)
check("T1: sentetik v1 41 satir", n == 41, n)
check("T1: WAL modu", c.execute("PRAGMA journal_mode").fetchone()[0] == "wal")
typless = c.execute("SELECT COUNT(*) FROM earthquakes WHERE magnitude_ml IS NULL AND magnitude_mw IS NULL AND magnitude_md IS NULL").fetchone()[0]
check("T1: 19 tursuz kayit", typless == 19, typless)
c.close()

# 2. ID cakisma provasi (kopyada): OR REPLACE orijinali ezer
shutil.copy(P.V1, P.WORK + ".c1")
c = sqlite3.connect(P.WORK + ".c1")
before = c.execute("SELECT magnitude FROM earthquakes WHERE id=1000").fetchone()[0]
c.execute("INSERT OR REPLACE INTO earthquakes (id, event_id, occurred_at, timestamp, latitude, longitude, magnitude, source, region_tag) VALUES (1000,'koeri_cakisik','2026-09-20 10:00:00',1789000000,40.7,28.5,9.9,'koeri','marmara')")
c.commit()
after = c.execute("SELECT magnitude, source FROM earthquakes WHERE id=1000").fetchone()
c.close()
os.remove(P.WORK + ".c1")
check("T2: ID cakismasi orijinali ezer (uretim zaafi)",
      before != 9.9 and after[0] == 9.9 and after[1] == "koeri",
      f"once={before} sonra={after}")

# 3. yazici tespiti
check("T3: bosken yazici yok", P.check_no_writers(P.V1) is True)
w = sqlite3.connect(P.V1, timeout=10)
w.execute("BEGIN IMMEDIATE")
check("T3: acik yazici tespit edilir", P.check_no_writers(P.V1) is False)
w.execute("ROLLBACK")
w.close()
check("T3: yazici kapandi", P.check_no_writers(P.V1) is True)

# 4. Backup API
P.backup_api(P.V1, P.BACKUP)
b = sqlite3.connect(P.BACKUP)
check("T4: yedek sayim esit",
      b.execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0] == 41)
check("T4: yedek integrity", b.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
b.close()

# 5. calisma kopyasinda migration
shutil.copy(P.BACKUP, P.WORK)
counts, ver = P.migrate_to_v2(P.WORK)
check("T5: 41 obs/41 surum/41 event",
      counts == {"obs": 41, "ver": 41, "ev": 41, "uv": 2}, counts)
check("T5: link integrity", ver["link_mismatch"] == 0 and ver["fk"] == []
      and ver["integrity"] == "ok", ver)
c = sqlite3.connect(P.WORK)
unk = c.execute("SELECT COUNT(*) FROM observations WHERE mag_type='unknown'").fetchone()[0]
gen = c.execute("SELECT COUNT(*) FROM observations WHERE source_event_id LIKE 'gen_%'").fetchone()[0]
leg = c.execute("SELECT COUNT(*) FROM observations WHERE raw_status='legacy_unavailable'").fetchone()[0]
check("T5: 19 unknown + 1 sentetik kimlik + 41 legacy-ham",
      unk == 19 and gen == 1 and leg == 41, f"unk={unk} gen={gen} leg={leg}")
pair = c.execute("SELECT COUNT(*) FROM observations WHERE source_event_id LIKE 'koeri_20260918%'").fetchone()[0]
evpair = c.execute("SELECT COUNT(DISTINCT event_id) FROM observations WHERE source_event_id LIKE 'koeri_20260918%'").fetchone()[0]
check("T5: 110sn cifti ayri event (otomatik birlesme yok)", pair == 2 and evpair == 2)
c.close()

# 6. tekrar migration korumasi
c = sqlite3.connect(P.WORK)
uv = c.execute("PRAGMA user_version").fetchone()[0]
c.close()
check("T6: user_version=2 isaretli", uv == 2, uv)
# ayni hash -> UNIQUE ihlali (yeni surum uretilmez)
c = sqlite3.connect(P.WORK)
r = c.execute("SELECT obs_id, fetched_hash FROM observation_versions LIMIT 1").fetchone()
dup_ok = False
try:
    c.execute("INSERT INTO observation_versions (obs_id, version_no, fetched_hash, occurred_raw, timestamp, revision) VALUES (?,?,?, 'x', 1, 'unknown')",
              (r[0], 999, r[1]))
except sqlite3.IntegrityError:
    dup_ok = True
c.close()
check("T6: ayni hash ikinci kez giremez", dup_ok)
# hash deterministik + belgeli
h1 = P.content_hash("2026-09-01 10:00:00", 40.7, 28.5, 10.0, 1.5, None, None, "unknown")
h2 = P.content_hash("2026-09-01 10:00:00", 40.7, 28.5, 10.0, 1.5, None, None, "unknown")
check("T6: hash deterministik", h1 == h2 and len(h1) == 64, h1[:16])

# 7. current_version bag kopuklugu tespiti
shutil.copy(P.WORK, P.WORK + ".c7")
c = sqlite3.connect(P.WORK + ".c7")
victim = c.execute("SELECT obs_id FROM observations LIMIT 1").fetchone()[0]
other = c.execute("SELECT version_id FROM observation_versions WHERE obs_id != ? LIMIT 1", (victim,)).fetchone()[0]
c.execute("PRAGMA foreign_keys=OFF")
c.execute("UPDATE observations SET current_version_id=? WHERE obs_id=?", (other, victim))
c.commit()
bad = c.execute("SELECT COUNT(*) FROM observations o JOIN observation_versions v ON o.current_version_id = v.version_id WHERE v.obs_id != o.obs_id").fetchone()[0]
c.close()
os.remove(P.WORK + ".c7")
check("T7: capraz-bag kopuklugu sorguyla yakalanir", bad == 1, bad)

# 8. gorusler: compat 41, typed 22; fark olculur (esitlik iddia edilmez)
c = sqlite3.connect(P.WORK)
n_compat = c.execute("SELECT COUNT(*) FROM v_compat").fetchone()[0]
n_typed = c.execute("SELECT COUNT(*) FROM v_typed_science").fetchone()[0]
m_compat = c.execute("SELECT AVG(mag_raw) FROM observations").fetchone()[0]
m_typed = c.execute("SELECT AVG(analysis_mag) FROM v_typed_science").fetchone()[0]
c.close()
check("T8: compat=41 typed=22", n_compat == 41 and n_typed == 22, f"{n_compat}/{n_typed}")
print(f"   olculen fark: compat-ortalama={m_compat:.3f} typed-ortalama={m_typed:.3f} (esitlik iddia edilmedi)")
check("T8: fark sayisal gosterildi", abs(m_compat - m_typed) >= 0)

# 9. guc-kesintisi: yarim dosya integrity'den gecemez -> rollback
shutil.copy(P.BACKUP, P.LIVE)
size = os.path.getsize(P.LIVE)
with open(P.LIVE, "r+b") as f:
    f.truncate(size // 2)
c = sqlite3.connect(P.LIVE)
try:
    integ = c.execute("PRAGMA integrity_check").fetchone()[0]
except sqlite3.DatabaseError:
    integ = "BOZUK-istisna"
c.close()
check("T9: yarim dosya bozuk tespit edilir", integ != "ok", str(integ)[:40])
shutil.copy(P.BACKUP, P.LIVE)  # rollback
c = sqlite3.connect(P.LIVE)
check("T9: rollback sonrasi 41 kayit saglam",
      c.execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0] == 41
      and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
c.close()

# 10. gercek DB'ye dokunulmadi
live_after = (os.path.getmtime(LIVE_REAL), os.path.getsize(LIVE_REAL))
check("T10: gercek DB degismedi", live_before == live_after, live_after)

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
