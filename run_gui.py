"""
Deprem Analiz - Marmara - GUI Başlatıcı
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deprem_izleme.gui import main

if __name__ == "__main__":
    main()
