"""
Deprem Analiz - Marmara - GUI Başlatıcı
"""
import sys
import os

if "--update-probe" in sys.argv:
    # Guncelleme saglik yoklamasi: surumu bas, cik (GUI acilmaz).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from deprem_izleme.version import __version__
    print(__version__)
    sys.exit(0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deprem_izleme.gui import main

if __name__ == "__main__":
    main()
