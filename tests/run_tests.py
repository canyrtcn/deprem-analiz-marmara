"""Kalıcı regresyon koşucusu (stdlib; pytest gerekmez).

Kullanim:  python tests/run_tests.py
- Her batarya ayrı süreçte, sentetik gecici dizinde (DEPREM_TESTTMP) calisir.
- Canlı DB'ye erisen surec db_guard tarafindan durdurulur (FAIL sayilir).
- Ag/TG cagrilari tum bataryalarda yamali ya da kapali tutulur.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
BATTERIES = [
    "test_db_state.py",
    "k3m1_guard_test.py",
    "fazb2_g1a_test.py",
    "fazb2_g1a_conc_test.py",
    "cli_exit_test.py",
    "g2p_test.py",
    "bitirme_test.py",
    "k3t_test.py",
    "k3m1_test.py",
    "k3m1_int_test.py",
    "fazb2_sec08k1_test.py",
    "fazb2_sec08k2_test.py",
    "fazb2_sec02_test.py",
    "fazb2_sec01_test.py",
    "fazb1_test.py",
    "faza_test.py",
    "faza_test2.py",
    "faza_test3.py",
    "faza_test4.py",
]


def main():
    tmp = tempfile.mkdtemp(prefix="deprem_tests_")
    # yardimci betikler (is parcaciklari) sentetik dizine kopyalanir
    for _f in os.listdir(HERE):
        if _f.endswith(".py") and "_test" not in _f and _f != "run_tests.py":
            try:
                import shutil as _sh
                _sh.copy(os.path.join(HERE, _f), os.path.join(tmp, _f))
            except Exception:
                pass
    env = dict(os.environ)
    env["DEPREM_SKIP_DB_INIT"] = "1"
    env["DEPREM_TESTTMP"] = tmp
    env["DEPREM_REPO_ROOT"] = REPO_ROOT
    env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
    total_pass, total_fail, rows = 0, 0, []
    for bat in BATTERIES:
        path = os.path.join(HERE, bat)
        try:
            src = open(path, encoding="utf-8").read()
        except Exception as e:
            rows.append((bat, "DOSYA-YOK", str(e)))
            total_fail += 1
            continue
        if "db_guard.install()" not in src or "DEPREM_SKIP_DB_INIT" not in src:
            rows.append((bat, "GUARD-YOK", "koruma kurulmadan calistirilmadi"))
            total_fail += 1
            continue
        try:
            p = subprocess.run([sys.executable, path], capture_output=True,
                               text=True, timeout=590, cwd=tmp, env=env)
            out = (p.stdout or "") + (p.stderr or "")
            npass = sum(1 for ln in out.splitlines() if ln.startswith("PASS"))
            nfail = sum(1 for ln in out.splitlines() if ln.startswith("FAIL"))
            ok = (p.returncode == 0 and nfail == 0 and ("TUMU PASS" in out))
            rows.append((bat, "PASS" if ok else "FAIL",
                         f"rc={p.returncode} +{npass}/-{nfail}"))
            if not ok:
                tail = "\n".join(out.splitlines()[-40:])
                print(f"--- {bat} CIKTI-SONU ---\n{tail}\n--- SON ---")
            total_pass += npass
            total_fail += nfail + (0 if ok else 1)
        except Exception as e:
            rows.append((bat, "HATA", str(e)[:120]))
            total_fail += 1
    print(f"{'BATARYA':28} {'DURUM':8} BILGI")
    for bat, st, info in rows:
        print(f"{bat:28} {st:8} {info}")
    print("=" * 64)
    print(f"TOPLAM: {total_pass} PASS / {total_fail} FAIL  (tmp: {tmp})")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
