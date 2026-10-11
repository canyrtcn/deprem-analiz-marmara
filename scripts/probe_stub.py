"""Guncelleme e2e test yardimcisi: sahte 'yeni exe'.

Kullanim (test tarafindan PyInstaller ile derlenir):
    probe.exe --update-probe   -> surumu basar, cikar (saglik yoklamasi)
    probe.exe --hold SN        -> SN saniye calisir (kilit senaryosu)
    probe.exe --crash          -> sifir-disi cikis (bozuk surum senaryosu)

Gercek dosya kilidi + gercek surec davranisi uretir; uretim kodu degildir.
"""
import sys
import time

STUB_VERSION = "9.9.9-test"


def main():
    if "--update-probe" in sys.argv:
        print(STUB_VERSION)
        return 0
    if "--crash" in sys.argv:
        print("bozuk")
        return 3
    if "--hold" in sys.argv:
        try:
            secs = int(sys.argv[sys.argv.index("--hold") + 1])
        except Exception:
            secs = 60
        time.sleep(max(1, secs))
        return 0
    # Bayraksiz (yardimcinin lansman bicimi): gercek GUI gibi yasayan
    # islemi taklit et; yasama dogrulamasi (12sn) icinde olmemeli.
    print(STUB_VERSION, flush=True)
    time.sleep(30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
