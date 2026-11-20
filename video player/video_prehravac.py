import sys 
import os
import json
import re
import time
from pathlib import Path

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QListWidget, QSlider, QPushButton, QLineEdit, QFileDialog,
    QInputDialog, QMessageBox, QMenu, QDialog, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QSize, QTimer, QUrl
from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QPixmap

try:
    from mutagen.mp3 import MP3
except ImportError:
    print("Knihovna Mutagen není nalezena. Nainstalujte ji: pip install mutagen")
    sys.exit()

import pygame

class LoadingScreen(QDialog):
    def __init__(self, assets_path):
        super().__init__()
        
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose) 
        
        video_file = assets_path / "loading.mp4"
        
        self.resize(800, 450)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.video_widget = QVideoWidget()
        layout.addWidget(self.video_widget)

        self.player = QMediaPlayer()
        self.player.setVideoOutput(self.video_widget)

        if not video_file.exists():
            print(f"'loading.mp4' nenalezeno ve složce {assets_path}.")
            QTimer.singleShot(0, self.close) 
            return

        self.player.setSource(QUrl.fromLocalFile(str(video_file.resolve())))
        
        self.player.mediaStatusChanged.connect(self.video_skoncilo)
        
        print("Spouštím loading video...")
        self.player.play()

    def video_skoncilo(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            print("Video dokončeno, spouštím aplikaci.")
            self.player.stop()
            self.close()

LRC_CAS_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")


def _parsuj_lrc(obsah):
    """Převede LRC na seřazený seznam (čas v sekundách, text)."""
    titulky = []
    for radek in obsah.splitlines():
        casy = LRC_CAS_RE.findall(radek)
        if not casy:
            continue
        text = LRC_CAS_RE.sub("", radek).strip()
        for minuty, sekundy, zlomek in casy:
            cas = int(minuty) * 60 + int(sekundy)
            if zlomek:
                cas += int(zlomek) / (10 ** len(zlomek))
            titulky.append((float(cas), text))
    titulky.sort(key=lambda polozka: polozka[0])
    return titulky


def _prosty_text(obsah):
    """Titulky bez časování – jen text po řádcích."""
    return [(None, radek.strip()) for radek in obsah.splitlines()]


def nacti_titulky(cesta_audio):
    """Hledá titulky vedle souboru (.lrc / .txt), jinak v ID3 tagu USLT."""
    cesta = Path(cesta_audio)

    for pripona in (".lrc", ".LRC"):
        kandidat = cesta.with_suffix(pripona)
        if kandidat.exists():
            return _parsuj_lrc(kandidat.read_text(encoding="utf-8", errors="ignore"))

    kandidat = cesta.with_suffix(".txt")
    if kandidat.exists():
        return _prosty_text(kandidat.read_text(encoding="utf-8", errors="ignore"))

    try:
        from mutagen.id3 import ID3

        for klic, frame in ID3(str(cesta)).items():
            if klic.startswith("USLT"):
                return _prosty_text(str(frame.text))
    except Exception:
        pass

    return []


def nacti_metadata(cesta_audio):
    """Vrací (název, interpret) z ID3 tagů, jinak z názvu souboru."""
    cesta = Path(cesta_audio)
    nazev, interpret = cesta.stem, ""
    try:
        from mutagen.id3 import ID3

        tagy = ID3(str(cesta))
        if tagy.get("TIT2"):
            nazev = str(tagy["TIT2"])
        if tagy.get("TPE1"):
            interpret = str(tagy["TPE1"])
    except Exception:
        pass
    return nazev, interpret


class NowPlayingScreen(QWidget):
    """Fullscreen obrazovka 'Nyní hraje' s titulky."""

    def __init__(self, hlavni_okno):
        super().__init__(hlavni_okno, Qt.Window)
        self.hlavni_okno = hlavni_okno
        self.titulky = []
        self.radky_popisku = []
        self.aktivni_radek = -1
        self.delka_sec = 0

        self.setWindowTitle("Nyní hraje")
        self.setStyleSheet("background-color: #0B0F1A; color: white;")

        hlavni_layout = QVBoxLayout(self)
        hlavni_layout.setContentsMargins(40, 20, 40, 25)
        hlavni_layout.setSpacing(12)

        lista = QHBoxLayout()
        zpet_btn = QPushButton(" Zpět do přehrávače")
        zpet_btn.setCursor(Qt.PointingHandCursor)
        if not hlavni_okno.icons["arrow_left"].isNull():
            zpet_btn.setIcon(hlavni_okno.icons["arrow_left"])
            zpet_btn.setIconSize(QSize(20, 20))
        zpet_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 8px 14px;
                border: none;
                border-radius: 8px;
                color: #B0B0B0;
                background-color: rgba(45, 50, 70, 160);
            }
            QPushButton:hover { color: white; background-color: rgba(70, 78, 105, 200); }
        """)
        zpet_btn.clicked.connect(self.hide)
        lista.addWidget(zpet_btn)
        lista.addStretch()
        hlavni_layout.addLayout(lista)

        self.obal_label = QLabel()
        self.obal_label.setAlignment(Qt.AlignCenter)
        if not hlavni_okno.icons["note"].isNull():
            self.obal_label.setPixmap(
                hlavni_okno.icons["note"].pixmap(QSize(110, 110))
            )
        hlavni_layout.addWidget(self.obal_label)

        self.nazev_label = QLabel("Nyní hraje")
        self.nazev_label.setAlignment(Qt.AlignCenter)
        self.nazev_label.setWordWrap(True)
        self.nazev_label.setFont(QFont("Segoe UI", 26, QFont.Bold))
        hlavni_layout.addWidget(self.nazev_label)

        self.interpret_label = QLabel("")
        self.interpret_label.setAlignment(Qt.AlignCenter)
        self.interpret_label.setStyleSheet("color: #8A94AD; font-size: 16px;")
        hlavni_layout.addWidget(self.interpret_label)

        self.titulky_scroll = QScrollArea()
        self.titulky_scroll.setWidgetResizable(True)
        self.titulky_scroll.setFrameShape(QFrame.NoFrame)
        self.titulky_scroll.setStyleSheet("background-color: transparent;")

        self.titulky_obsah = QWidget()
        self.titulky_obsah.setStyleSheet("background-color: transparent;")
        self.titulky_layout = QVBoxLayout(self.titulky_obsah)
        self.titulky_layout.setContentsMargins(0, 0, 0, 0)
        self.titulky_layout.setSpacing(2)
        self.titulky_scroll.setWidget(self.titulky_obsah)
        hlavni_layout.addWidget(self.titulky_scroll, 1)

        self.cas_label = QLabel("0:00")
        self.cas_label.setStyleSheet("color: #8A94AD;")
        self.delka_label = QLabel("0:00")
        self.delka_label.setStyleSheet("color: #8A94AD;")

        self.pozice_slider = QSlider(Qt.Orientation.Horizontal)
        self.pozice_slider.setRange(0, 0)
        self.pozice_slider.sliderReleased.connect(self._pozadavek_na_pozici)

        prubeh = QHBoxLayout()
        prubeh.addWidget(self.cas_label)
        prubeh.addWidget(self.pozice_slider, 1)
        prubeh.addWidget(self.delka_label)
        hlavni_layout.addLayout(prubeh)

        ovladani = QHBoxLayout()
        ovladani.addStretch()

        self.zpet_skladba_btn = QPushButton()
        self.prepinac_btn = QPushButton()
        self.dalsi_skladba_btn = QPushButton()
        for tlacitko, ikona, slot, tip in (
            (self.zpet_skladba_btn, "arrow_left", self.hlavni_okno.predchozi_skladba, "Předchozí skladba"),
            (self.prepinac_btn, "play", self.hlavni_okno.prepnout_prehravani, "Přehrát / pozastavit"),
            (self.dalsi_skladba_btn, "arrow_right", self.hlavni_okno.pustit_dalsi_skladbu, "Další skladba"),
        ):
            tlacitko.setIcon(hlavni_okno.icons.get(ikona, QIcon()))
            tlacitko.setIconSize(QSize(34, 34))
            tlacitko.setFixedSize(QSize(56, 56))
            tlacitko.setToolTip(tip)
            tlacitko.setStyleSheet("""
                QPushButton { border: none; border-radius: 28px; background-color: rgba(45, 50, 70, 160); }
                QPushButton:hover { background-color: rgba(0, 191, 255, 90); }
            """)
            tlacitko.clicked.connect(slot)
            ovladani.addWidget(tlacitko)

        ovladani.addStretch()
        hlavni_layout.addLayout(ovladani)

        napoveda = QLabel("Mezerník = pauza · ← → = posun o 5 s · Esc = zpět")
        napoveda.setAlignment(Qt.AlignCenter)
        napoveda.setStyleSheet("color: #5A6684; font-size: 13px;")
        hlavni_layout.addWidget(napoveda)

    def zobrazit_fullscreen(self):
        if not self.isVisible():
            self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def nastavit_skladbu(self, nazev, interpret, titulky, delka_sec):
        self.nazev_label.setText(nazev)
        self.interpret_label.setText(interpret or "Neznámý interpret")
        self.delka_sec = delka_sec
        self.delka_label.setText(self.hlavni_okno.format_time(delka_sec))
        self.pozice_slider.setRange(0, max(0, int(delka_sec)))
        self.pozice_slider.setValue(0)
        self.cas_label.setText("0:00")
        self.titulky = titulky or []
        self._vytvorit_radky()
        self.titulky_scroll.verticalScrollBar().setValue(0)
        self.nastavit_stav_prehravani(True)

    def nastavit_stav_prehravani(self, hraje):
        ikona = "pause" if hraje else "play"
        self.prepinac_btn.setIcon(self.hlavni_okno.icons.get(ikona, QIcon()))

    @staticmethod
    def _styl_radku(aktivni):
        if aktivni:
            return "color: #00BFFF; font-size: 24px; font-weight: bold; padding: 8px;"
        return "color: #9AA3BA; font-size: 19px; padding: 8px;"

    def _vytvorit_radky(self):
        while self.titulky_layout.count():
            polozka = self.titulky_layout.takeAt(0)
            widget = polozka.widget()
            if widget is not None:
                widget.deleteLater()
        self.radky_popisku = []
        self.aktivni_radek = -1

        self.titulky_layout.addStretch()

        if not self.titulky:
            prazdno = QLabel(
                "Titulky nejsou k dispozici.\n"
                "Přidej k písničce soubor .lrc (s časováním) nebo .txt se stejným názvem."
            )
            prazdno.setAlignment(Qt.AlignCenter)
            prazdno.setWordWrap(True)
            prazdno.setStyleSheet("color: #6C7A99; font-size: 17px; padding: 20px;")
            self.titulky_layout.addWidget(prazdno)
        else:
            for _, text in self.titulky:
                radek = QLabel(text if text else " ")
                radek.setWordWrap(True)
                radek.setAlignment(Qt.AlignCenter)
                radek.setStyleSheet(self._styl_radku(False))
                self.titulky_layout.addWidget(radek)
                self.radky_popisku.append(radek)

        self.titulky_layout.addStretch()

    def aktualizovat_prubeh(self, pozice_sec):
        self.pozice_slider.blockSignals(True)
        self.pozice_slider.setValue(int(pozice_sec))
        self.pozice_slider.blockSignals(False)
        self.cas_label.setText(self.hlavni_okno.format_time(pozice_sec))
        self._zvyraznit_radek(pozice_sec)

    def _zvyraznit_radek(self, pozice_sec):
        if not self.titulky or self.titulky[0][0] is None:
            return

        novy_index = -1
        for index, (cas, _) in enumerate(self.titulky):
            if cas is not None and cas <= pozice_sec:
                novy_index = index

        if novy_index == self.aktivni_radek:
            return

        if 0 <= self.aktivni_radek < len(self.radky_popisku):
            self.radky_popisku[self.aktivni_radek].setStyleSheet(self._styl_radku(False))

        self.aktivni_radek = novy_index

        if 0 <= novy_index < len(self.radky_popisku):
            radek = self.radky_popisku[novy_index]
            radek.setStyleSheet(self._styl_radku(True))
            self.titulky_scroll.ensureWidgetVisible(radek, 0, 140)

    def _pozadavek_na_pozici(self):
        self.hlavni_okno.posunout_pozici_na(self.pozice_slider.value())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
        elif event.key() == Qt.Key_Space:
            self.hlavni_okno.prepnout_prehravani()
        elif event.key() == Qt.Key_Right:
            self.hlavni_okno.posunout_pozici_na(min(self.pozice_slider.value() + 5, self.delka_sec))
        elif event.key() == Qt.Key_Left:
            self.hlavni_okno.posunout_pozici_na(max(self.pozice_slider.value() - 5, 0))
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class ModerniPrehravac(QMainWindow):
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(" Craftora player v2.21")
        self.setGeometry(100, 100, 1366, 768)
        
        pygame.mixer.init()
        self.current_track = None
        self.current_song_duration_sec = 0
        self.pozice_skladby_sec = 0.0
        self.cas_startu_prehravani = None
        
        script_dir = Path(__file__).parent.resolve()
        self.assets_path = script_dir / "assets"
        self.playlists_file = script_dir / "playlists.json"
        
        self.icons = {} 
        self.track_library = {} 
        self.playlists = {}     
        self.currently_viewing_paths = [] 
        self.repeat_mode = 0 
        
        # Nová proměnná pro řízení stavu bočního menu
        self.sidebar_mode = "HOME" # Může být "HOME" nebo "PLAYLISTS"

        self.timer = QTimer(self)
        self.timer.setInterval(500) 
        self.timer.timeout.connect(self.aktualizovat_progress)
        
        self.nacist_ikony() 
        self.load_playlists_from_file() 

        self.nastavit_tmavy_styl()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        self.nastavit_pozadi(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        content_layout = QHBoxLayout()
        
        self.sidebar_widget = self.vytvorit_sidebar()
        content_layout.addWidget(self.sidebar_widget, 2)
        
        self.central_content_widget, self.song_list_widget = self.vytvorit_centralni_obsah()
        content_layout.addWidget(self.central_content_widget, 5) 
        
        main_layout.addLayout(content_layout, 1)

        self.player_bar = self.vytvorit_player_bar()
        main_layout.addWidget(self.player_bar)
        
        self.now_playing = NowPlayingScreen(self)
        
        self.skenovat_lokalni_hudbu() 
        self.aktualizovat_playlist_list() 
        
        # Inicializujeme sidebar po vytvoření widgetů pro playlisty
        self.prepnout_sidebar_mode(self.sidebar_mode)
        
        if self.playlist_list_widget.count() > 0:
            self.zobrazit_playlist(self.playlist_list_widget.item(0))


    def nacist_ikony(self):
        icon_names = {
            "arrow_left": "arrow_left.png",
            "arrow_right": "arrow_right.png",
            "play": "play.png",
            "pause": "pause.png",
            "note": "note.png",
            "logo": "logo.png",
            "search": "search.png",
            "volume": "volume.png",
            "volume_mute": "volume_mute.png",
            "repeat_none": "repeat_none.png", 
            "repeat_all": "repeat_all.png",   
            "repeat_one": "repeat_one.png",
            "home": "home.png", 
            "grid": "grid.png", 
            "user": "user.png",
            "playlist_menu": "playlist_menu.png",
            "arrow_back": "arrow_left.png" # Použijeme stávající ikonu pro návrat
        }
        
        for key, filename in icon_names.items():
            icon_path = self.assets_path / filename
            if icon_path.exists():
                self.icons[key] = QIcon(str(icon_path))
            else:
                self.icons[key] = QIcon()

        if not self.icons.get("logo", QIcon()).isNull():
            logo_size = QSize(48, 48)
            pixmap = QPixmap(str(self.assets_path / "logo.png"))
            if not pixmap.isNull():
                self.icons["logo_pixmap"] = pixmap.scaled(logo_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


    def nastavit_tmavy_styl(self):
        dark_palette = QPalette()
        WINDOW_COLOR = QColor(25, 30, 45, 180) 
        BASE_COLOR = QColor(35, 40, 60, 200)
        HIGHLIGHT_COLOR = QColor(0, 191, 255) 
        dark_palette.setColor(QPalette.Window, WINDOW_COLOR)
        dark_palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.Base, BASE_COLOR)
        dark_palette.setColor(QPalette.Text, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.Button, QColor(45, 50, 70))
        dark_palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.Highlight, HIGHLIGHT_COLOR) 
        dark_palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
        QApplication.setPalette(dark_palette)


    def nastavit_pozadi(self, widget):
        background_image_path = self.assets_path / "background.jpg"
        if background_image_path.exists():
            absolute_path = background_image_path.resolve().as_posix()
            style_sheet = f"""
                QMainWindow {{
                    background-image: url({absolute_path});
                    background-repeat: no-repeat;
                    background-position: center;
                }}
            """
            self.setStyleSheet(style_sheet)


    def vytvorit_menu_polozku(self, nazev, ikona_key, mode_name=None):
        btn = QPushButton(nazev)
        btn.setFont(QFont("Segoe UI", 12))
        btn.setFlat(True)
        btn.setIcon(self.icons.get(ikona_key, QIcon()))
        btn.setIconSize(QSize(20, 20))
        
        style = """
            QPushButton {
                text-align: left;
                padding: 10px 15px;
                border: none;
                color: #B0B0B0;
                background-color: transparent;
            }
            QPushButton:hover {
                color: white;
                background-color: rgba(60, 65, 85, 150);
                border-radius: 8px;
            }
        """
        
        if mode_name and mode_name == self.sidebar_mode:
            style = """
                QPushButton {
                    text-align: left;
                    padding: 10px 15px;
                    border: none;
                    color: #FFFFFF;
                    background-color: rgba(0, 191, 255, 80); 
                    border-left: 4px solid #00BFFF;
                    border-radius: 8px;
                }
            """
            
        btn.setStyleSheet(style)
        
        if mode_name:
            btn.clicked.connect(lambda: self.prepnout_sidebar_mode(mode_name))
        
        return btn

    # Nová řídící metoda pro přepínání obsahu panelu
    def prepnout_sidebar_mode(self, mode):
        self.sidebar_mode = mode
        
        # Aktualizujeme vzhled tlačítek (zvýraznění aktivní sekce)
        self.home_btn.setStyleSheet(self.vytvorit_menu_polozku("Home", "home", "HOME").styleSheet())
        self.categories_btn.setStyleSheet(self.vytvorit_menu_polozku("Categories", "grid", "CATEGORIES").styleSheet())
        self.artists_btn.setStyleSheet(self.vytvorit_menu_polozku("Artists", "user", "ARTISTS").styleSheet())
        self.playlists_main_btn.setStyleSheet(self.vytvorit_menu_polozku("Playlists", "playlist_menu", "PLAYLISTS").styleSheet())

        # Zobrazíme/skryjeme příslušné sekce
        is_playlists = (mode == "PLAYLISTS")
        self.playlist_management_container.setVisible(is_playlists)
        self.nav_menu_container.setVisible(not is_playlists)

        # Můžeme také aktualizovat centrální obsah, ale pro tuto verzi jen přepneme menu.

    def vytvorit_playlist_management_panel(self):
        """Vytvoří widget obsahující vše pro správu playlistů."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Tlačítko zpět
        back_btn = self.vytvorit_menu_polozku("Zpět do menu", "arrow_back")
        back_btn.clicked.connect(lambda: self.prepnout_sidebar_mode("HOME"))
        layout.addWidget(back_btn)
        
        # Tlačítka správy
        management_layout = QHBoxLayout()
        create_playlist_btn = QPushButton("Vytvořit")
        create_playlist_btn.clicked.connect(self.vytvorit_novy_playlist)
        delete_playlist_btn = QPushButton("Smazat")
        delete_playlist_btn.clicked.connect(self.smazat_playlist)
        scan_button = QPushButton("Skenovat složku")
        scan_button.clicked.connect(self.vybrat_slozku_pro_skenovani)
        
        for btn in [create_playlist_btn, delete_playlist_btn, scan_button]:
            btn.setStyleSheet("""
                QPushButton {
                    padding: 5px; 
                    border: 1px solid #354060; 
                    border-radius: 4px;
                    background-color: #354060;
                }
                QPushButton:hover {
                    background-color: #455070;
                }
            """)
            management_layout.addWidget(btn)
        
        layout.addLayout(management_layout)

        # List widget pro playlisty
        self.playlist_list_widget = QListWidget()
        self.playlist_list_widget.itemClicked.connect(self.zobrazit_playlist)
        self.playlist_list_widget.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: transparent;
                padding-left: 5px; 
            }
            QListWidget::item {
                padding: 5px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: rgba(0, 191, 255, 50); 
                color: white;
            }
        """)
        layout.addWidget(self.playlist_list_widget)
        layout.addStretch()
        
        return container

    def vytvorit_sidebar(self):
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar.setFixedWidth(250)
        sidebar.setStyleSheet("background-color: rgba(30, 35, 50, 180); border-radius: 5px;")
        
        # 1. Logo/Název
        if "logo_pixmap" in self.icons:
            logo_label = QLabel()
            logo_label.setPixmap(self.icons["logo_pixmap"])
            logo_label.setAlignment(Qt.AlignCenter)
            sidebar_layout.addWidget(logo_label)

        # 2. Kontejner pro hlavní navigační menu
        self.nav_menu_container = QWidget()
        nav_layout = QVBoxLayout(self.nav_menu_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)

        # Tlačítka hlavního menu (uložená jako self atributy pro pozdější změnu stylu)
        self.home_btn = self.vytvorit_menu_polozku("Home", "home", "HOME")
        self.categories_btn = self.vytvorit_menu_polozku("Categories", "grid", "CATEGORIES")
        self.artists_btn = self.vytvorit_menu_polozku("Artists", "user", "ARTISTS")
        self.playlists_main_btn = self.vytvorit_menu_polozku("Playlists", "playlist_menu", "PLAYLISTS")
        
        nav_layout.addWidget(self.home_btn)
        nav_layout.addWidget(self.categories_btn)
        nav_layout.addWidget(self.artists_btn)
        nav_layout.addWidget(self.playlists_main_btn)
        nav_layout.addStretch()
        
        sidebar_layout.addWidget(self.nav_menu_container)

        # 3. Kontejner pro správu playlistů (zpočátku skrytý)
        self.playlist_management_container = self.vytvorit_playlist_management_panel()
        self.playlist_management_container.setVisible(False)
        sidebar_layout.addWidget(self.playlist_management_container)
        
        sidebar_layout.addStretch()
        
        return sidebar
        
    def vytvorit_centralni_obsah(self):
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central.setStyleSheet("background-color: rgba(45, 50, 70, 180); border-radius: 5px;")
        
        self.content_title_label = QLineEdit()
        self.content_title_label.setFont(QFont("Segoe UI", 24, QFont.Bold))
        self.content_title_label.setPlaceholderText("Vyhledat v knihovně")
        
        self.content_title_label.setStyleSheet("""
            QLineEdit {
                padding: 10px; 
                border: 2px solid rgba(0, 0, 0, 0); 
                background-color: transparent; 
            }
        """)
        
        if not self.icons["search"].isNull():
            search_icon = self.icons["search"]
            pixmap = search_icon.pixmap(QSize(28, 28)) 
            self.content_title_label.addAction(QIcon(pixmap), QLineEdit.LeadingPosition)

        self.content_title_label.textChanged.connect(self.filtrovat_skladby)
        central_layout.addWidget(self.content_title_label)
        
        song_list = QListWidget()
        song_list.setFont(QFont("Segoe UI", 11))
        
        song_list.itemClicked.connect(self.pustit_vybranou_skladbu)
        
        song_list.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: transparent;
            }
            QListWidget::item {
                background-color: rgba(60, 65, 85, 200); 
                border-radius: 8px; 
                padding: 10px; 
                margin-bottom: 8px; 
            }
            QListWidget::item:selected {
                background-color: #0078D7; 
                color: white;
            }
            QListWidget::item:hover {
                background-color: rgba(80, 85, 105, 220);
            }
        """)
        
        song_list.setContextMenuPolicy(Qt.CustomContextMenu)
        song_list.customContextMenuRequested.connect(self.zobrazit_menu_pro_pridani)
        
        central_layout.addWidget(song_list)
        
        return central, song_list
        
    def vytvorit_player_bar(self):
        player_bar = QWidget()
        player_bar.setFixedHeight(100) 
        player_bar.setStyleSheet("background-color: rgb(30, 35, 55); border-top-left-radius: 10px; border-top-right-radius: 10px;")
        
        main_player_layout = QVBoxLayout(player_bar)
        main_player_layout.setContentsMargins(10, 5, 10, 5)
        
        progress_layout = QHBoxLayout()
        self.time_label = QLabel("0:00")
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.sliderReleased.connect(self.posunout_pozici)
        self.duration_label = QLabel("0:00")
        
        progress_layout.addWidget(self.time_label)
        progress_layout.addWidget(self.position_slider)
        progress_layout.addWidget(self.duration_label)
        
        controls_layout = QHBoxLayout()
        
        self.song_info_label = QLabel()
        if not self.icons["note"].isNull():
            self.song_info_label.setPixmap(self.icons["note"].pixmap(QSize(20,20)))
        self.song_info_label.setText(" Zvolte skladbu")
        self.song_info_label.setFixedWidth(300)
        
        controls_layout.addWidget(self.song_info_label)
        controls_layout.addStretch()

        icon_size = QSize(32, 32)
        btn_size = QSize(40, 40)

        prev_button = QPushButton()
        if not self.icons["arrow_left"].isNull():
            prev_button.setIcon(self.icons["arrow_left"])
            prev_button.setIconSize(icon_size)
            prev_button.setFixedSize(btn_size)
        prev_button.setToolTip("Předchozí skladba")
        prev_button.clicked.connect(self.predchozi_skladba)
        controls_layout.addWidget(prev_button)

        self.play_button = QPushButton()
        if not self.icons["play"].isNull():
            self.play_button.setIcon(self.icons["play"])
            self.play_button.setIconSize(icon_size)
            self.play_button.setFixedSize(btn_size)
        self.play_button.clicked.connect(self.prepnout_prehravani)
        controls_layout.addWidget(self.play_button) 
        
        next_button = QPushButton()
        if not self.icons["arrow_right"].isNull():
            next_button.setIcon(self.icons["arrow_right"])
            next_button.setIconSize(icon_size)
            next_button.setFixedSize(btn_size)
        next_button.setToolTip("Další skladba")
        next_button.clicked.connect(self.pustit_dalsi_skladbu)
        controls_layout.addWidget(next_button)

        controls_layout.addStretch()

        self.repeat_button = QPushButton()
        self.repeat_button.setIconSize(icon_size)
        self.repeat_button.setFixedSize(btn_size)
        self.repeat_button.clicked.connect(self.prepnout_repeat_mode)
        controls_layout.addWidget(self.repeat_button)
        self.aktualizovat_repeat_ikonu()

        self.volume_label = QLabel()
        if not self.icons["volume"].isNull():
            self.volume_label.setPixmap(self.icons["volume"].pixmap(QSize(20,20)))
        controls_layout.addWidget(self.volume_label)
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70) 
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.valueChanged.connect(self.zmenit_hlasitost)
        self.zmenit_hlasitost(70) 
        controls_layout.addWidget(self.volume_slider)

        fullscreen_button = QPushButton("Titulky")
        fullscreen_button.setToolTip("Otevřít obrazovku Nyní hraje s titulky")
        fullscreen_button.setCursor(Qt.PointingHandCursor)
        fullscreen_button.setStyleSheet("""
            QPushButton {
                padding: 6px 14px;
                border: none;
                border-radius: 8px;
                color: #B0B0B0;
                background-color: rgba(60, 65, 85, 150);
            }
            QPushButton:hover { color: white; background-color: rgba(0, 191, 255, 90); }
        """)
        fullscreen_button.clicked.connect(self.otevrit_now_playing)
        controls_layout.addWidget(fullscreen_button)
        
        main_player_layout.addLayout(progress_layout)
        main_player_layout.addLayout(controls_layout)

        return player_bar
    
    def format_time(self, seconds):
        if seconds is None:
            return "0:00"
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes}:{seconds:02d}"

    def skenovat_lokalni_hudbu(self, cesta=None):
        if cesta is None:
            script_dir = Path(__file__).parent.resolve()
            cesta = script_dir / "MojeHudba" 
            if not cesta.exists():
                cesta.mkdir(exist_ok=True)
                
        print(f"Skenuji MP3 soubory v: {cesta.resolve()}")
                
        self.track_library.clear() 
        for soubor in cesta.glob("*.mp3"):
            path_str = str(soubor.resolve())
            self.track_library[path_str] = soubor.name 
            
        self.playlists["⭐ All Tracks"] = list(self.track_library.keys())

    def vybrat_slozku_pro_skenovani(self):
        cesta = QFileDialog.getExistingDirectory(self, "Vyberte složku s hudbou")
        if cesta:
            self.skenovat_lokalni_hudbu(Path(cesta))
            self.aktualizovat_playlist_list()
            # Po skenování zůstaneme v režimu playlistů
            self.prepnout_sidebar_mode("PLAYLISTS")
            self.zobrazit_playlist(self.playlist_list_widget.item(0))

    def load_playlists_from_file(self):
        if self.playlists_file.exists():
            try:
                with open(self.playlists_file, 'r', encoding='utf-8') as f:
                    self.playlists = json.load(f)
            except json.JSONDecodeError:
                print("Chyba při čtení playlists.json, vytvářím nový.")
                self.playlists = {}
        
        if "⭐ All Tracks" not in self.playlists:
            self.playlists["⭐ All Tracks"] = []
            
    def save_playlists_to_file(self):
        with open(self.playlists_file, 'w', encoding='utf-8') as f:
            json.dump(self.playlists, f, indent=4)
            
    def aktualizovat_playlist_list(self):
        self.playlist_list_widget.clear()
        self.playlist_list_widget.addItem("⭐ All Tracks")
        for name in self.playlists.keys():
            if name != "⭐ All Tracks":
                self.playlist_list_widget.addItem(name)
        
        self.playlist_list_widget.setCurrentRow(0)

    def vytvorit_novy_playlist(self):
        text, ok = QInputDialog.getText(self, "Nový Playlist", "Zadejte název playlistu:")
        if ok and text:
            if text in self.playlists:
                QMessageBox.warning(self, "Chyba", "Playlist s tímto názvem již existuje.")
            else:
                self.playlists[text] = [] 
                self.aktualizovat_playlist_list()
                self.save_playlists_to_file()
                print(f"Vytvořen playlist: {text}")

    def smazat_playlist(self):
        current_item = self.playlist_list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Chyba", "Musíte vybrat playlist ke smazání.")
            return

        nazev = current_item.text()
        if nazev == "⭐ All Tracks":
            QMessageBox.warning(self, "Chyba", "Nelze smazat 'All Tracks'.")
            return
        
        reply = QMessageBox.question(self, "Smazat Playlist", f"Opravdu chcete smazat playlist '{nazev}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            del self.playlists[nazev]
            self.aktualizovat_playlist_list()
            self.save_playlists_to_file()
            self.zobrazit_playlist(self.playlist_list_widget.item(0))
            print(f"Smazán playlist: {nazev}")

    def zobrazit_playlist(self, item):
        if not item: 
            if self.playlist_list_widget.count() > 0:
                self.playlist_list_widget.setCurrentRow(0)
                item = self.playlist_list_widget.item(0)
            else:
                self.content_title_label.setPlaceholderText("Vyhledat v knihovně")
                self.content_title_label.setText("") 
                self.song_list_widget.clear()
                self.currently_viewing_paths = []
                return

        nazev = item.text()
        
        self.content_title_label.setText("")
        
        if nazev == "⭐ All Tracks":
            self.content_title_label.setPlaceholderText("Vyhledat v knihovně")
        else:
            self.content_title_label.setPlaceholderText(f"Vyhledat v playlistu: {nazev}")
            
        self.song_list_widget.clear()
        
        if nazev in self.playlists:
            self.currently_viewing_paths = self.playlists[nazev]
            
            for path_str in self.currently_viewing_paths:
                filename = self.track_library.get(path_str, Path(path_str).name)
                self.song_list_widget.addItem(filename)
        else:
            self.currently_viewing_paths = []
            
    def filtrovat_skladby(self, text):
        text = text.lower()
        for i in range(self.song_list_widget.count()):
            item = self.song_list_widget.item(i)
            item.setHidden(text not in item.text().lower())

    def zobrazit_menu_pro_pridani(self, pos):
        item = self.song_list_widget.itemAt(pos)
        if not item:
            return 

        menu = QMenu()
        add_to_playlist_menu = menu.addMenu("Přidat do playlistu...")

        for playlist_name in self.playlists.keys():
            if playlist_name == "⭐ All Tracks":
                continue
            
            action = add_to_playlist_menu.addAction(playlist_name)
            action.triggered.connect(lambda checked=False, p=playlist_name: self.pridat_skladbu_do_playlistu(p))
            
        menu.exec(self.song_list_widget.mapToGlobal(pos))

    def pridat_skladbu_do_playlistu(self, playlist_name):
        selected_row = self.song_list_widget.currentRow()
        if selected_row == -1:
            return

        if selected_row >= len(self.currently_viewing_paths):
            print("Chyba: Index mimo rozsah při přidávání do playlistu.")
            return

        path_to_add = self.currently_viewing_paths[selected_row]
        
        if path_to_add not in self.playlists[playlist_name]:
            self.playlists[playlist_name].append(path_to_add)
            self.save_playlists_to_file()
            print(f"Skladba přidána do '{playlist_name}'.")
            
    def aktualizovat_repeat_ikonu(self):
        if self.repeat_mode == 0:
            self.repeat_button.setIcon(self.icons.get("repeat_none", QIcon()))
            self.repeat_button.setToolTip("Opakování vypnuto")
        elif self.repeat_mode == 1:
            self.repeat_button.setIcon(self.icons.get("repeat_all", QIcon()))
            self.repeat_button.setToolTip("Opakovat playlist")
        else: 
            self.repeat_button.setIcon(self.icons.get("repeat_one", QIcon()))
            self.repeat_button.setToolTip("Opakovat jednu skladbu")

    def prepnout_repeat_mode(self):
        self.repeat_mode = (self.repeat_mode + 1) % 3
        self.aktualizovat_repeat_ikonu()
        print(f"Režim opakování přepnut na: {self.repeat_mode}")

    def pustit_dalsi_skladbu(self):
        if self.current_track is None or not self.currently_viewing_paths:
            return

        try:
            current_index = self.currently_viewing_paths.index(self.current_track)
        except ValueError:
            current_index = -1
        
        if self.repeat_mode == 2: 
            next_index = current_index
        elif self.repeat_mode == 1: 
            next_index = (current_index + 1) % len(self.currently_viewing_paths)
        else: 
            next_index = current_index + 1
            if next_index >= len(self.currently_viewing_paths):
                pygame.mixer.music.stop()
                self.timer.stop()
                if not self.icons["play"].isNull():
                    self.play_button.setIcon(self.icons["play"])
                self.song_info_label.setText(" Přehrávání dokončeno")
                self.position_slider.setValue(0)
                self.time_label.setText(self.format_time(0))
                self.now_playing.nastavit_stav_prehravani(False)
                self.current_track = None
                return
        
        self.song_list_widget.setCurrentRow(next_index)
        self.pustit_vybranou_skladbu(otevrit_obrazovku=self.now_playing.isVisible())

    def otevrit_now_playing(self):
        if self.current_track is None:
            index = self.song_list_widget.currentRow()
            if index == -1:
                QMessageBox.information(self, "Nic nehraje", "Nejdřív vyber skladbu, kterou chceš přehrát.")
                return
            self.pustit_vybranou_skladbu()
            return
        self.now_playing.nastavit_stav_prehravani(pygame.mixer.music.get_busy())
        self.now_playing.zobrazit_fullscreen()
            
    def pustit_vybranou_skladbu(self, item=None, otevrit_obrazovku=True):
        try:
            if item is not None:
                index = self.song_list_widget.row(item)
            else:
                index = self.song_list_widget.currentRow()

            if index == -1 or index >= len(self.currently_viewing_paths):
                return

            cela_cesta = self.currently_viewing_paths[index]
            
            if not Path(cela_cesta).exists():
                QMessageBox.warning(self, "Chyba souboru", "Soubor nebyl nalezen. Možná byl přesunut nebo smazán.")
                return

            self.current_track = cela_cesta
            self.pozice_skladby_sec = 0
            
            try:
                audio = MP3(cela_cesta)
                self.current_song_duration_sec = int(audio.info.length)
            except Exception as e:
                print(f"Chyba Mutagen při čtení délky: {e}")
                self.current_song_duration_sec = 0
            
            self.position_slider.setRange(0, self.current_song_duration_sec)
            self.duration_label.setText(self.format_time(self.current_song_duration_sec))

            pygame.mixer.music.load(cela_cesta)
            pygame.mixer.music.play()
            self.cas_startu_prehravani = time.monotonic()
            self.timer.start() 
            
            if not self.icons["pause"].isNull():
                self.play_button.setIcon(self.icons["pause"])
            self.song_info_label.setText(f" Nyní hraje: {Path(cela_cesta).name}")

            nazev, interpret = nacti_metadata(cela_cesta)
            self.now_playing.nastavit_skladbu(
                nazev, interpret, nacti_titulky(cela_cesta), self.current_song_duration_sec
            )
            if otevrit_obrazovku:
                self.now_playing.zobrazit_fullscreen()
            
        except pygame.error as e:
            self.song_info_label.setText("CHYBA: Nelze přehrát soubor.")
            print(f"Chyba Pygame: {e}")

    def predchozi_skladba(self):
        if self.current_track is None or not self.currently_viewing_paths:
            return

        try:
            current_index = self.currently_viewing_paths.index(self.current_track)
        except ValueError:
            current_index = 0

        if current_index <= 0:
            next_index = 0
        else:
            next_index = current_index - 1

        self.song_list_widget.setCurrentRow(next_index)
        self.pustit_vybranou_skladbu(otevrit_obrazovku=self.now_playing.isVisible())
            
    def prepnout_prehravani(self):
        if self.current_track is None:
            self.pustit_vybranou_skladbu()
            return
            
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.timer.stop() 
            if not self.icons["play"].isNull():
                self.play_button.setIcon(self.icons["play"])
            self.now_playing.nastavit_stav_prehravani(False)
        else:
            pygame.mixer.music.unpause()
            self.cas_startu_prehravani = time.monotonic() - self.pozice_skladby_sec
            self.timer.start() 
            if not self.icons["pause"].isNull():
                self.play_button.setIcon(self.icons["pause"])
            self.now_playing.nastavit_stav_prehravani(True)
            
    def zmenit_hlasitost(self, hodnota):
        uroven = hodnota / 100.0
        pygame.mixer.music.set_volume(uroven)
        
        if hodnota == 0 and not self.icons["volume_mute"].isNull():
            self.volume_label.setPixmap(self.icons["volume_mute"].pixmap(QSize(20,20)))
        elif not self.icons["volume"].isNull():
            self.volume_label.setPixmap(self.icons["volume"].pixmap(QSize(20,20)))
    
    def aktualizovat_progress(self):
        if self.current_track is None:
            return

        if pygame.mixer.music.get_busy():
            if self.cas_startu_prehravani is not None:
                self.pozice_skladby_sec = time.monotonic() - self.cas_startu_prehravani
        elif self.current_song_duration_sec > 0 and self.pozice_skladby_sec >= self.current_song_duration_sec - 1:
            self.pustit_dalsi_skladbu()
            return

        current_time_sec = int(min(self.pozice_skladby_sec, self.current_song_duration_sec))

        self.position_slider.blockSignals(True)
        self.position_slider.setValue(current_time_sec)
        self.position_slider.blockSignals(False)

        self.time_label.setText(self.format_time(current_time_sec))
        self.now_playing.aktualizovat_prubeh(current_time_sec)

    def posunout_pozici(self):
        self.posunout_pozici_na(self.position_slider.value())

    def posunout_pozici_na(self, pozice_sec):
        if not self.current_track:
            return

        pozice_sec = max(0, min(int(pozice_sec), self.current_song_duration_sec))

        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(self.current_track)
            pygame.mixer.music.play(start=pozice_sec)

            self.pozice_skladby_sec = pozice_sec
            self.cas_startu_prehravani = time.monotonic() - pozice_sec
            self.timer.start()
            if not self.icons["pause"].isNull():
                self.play_button.setIcon(self.icons["pause"])

            self.time_label.setText(self.format_time(pozice_sec))
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(pozice_sec)
            self.position_slider.blockSignals(False)
            self.now_playing.aktualizovat_prubeh(pozice_sec)
        except pygame.error as e:
            print(f"Chyba při přeskakování (seek): {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion") 

    script_dir = Path(__file__).parent.resolve()
    assets_path = script_dir / "assets"

    loader = LoadingScreen(assets_path)
    
    try:
        screen_geometry = app.primaryScreen().geometry()
        loader.move(
            (screen_geometry.width() - loader.width()) // 2,
            (screen_geometry.height() - loader.height()) // 2
        )
    except AttributeError:
        loader.resize(800, 450)

    loader.show()
    loader.exec() 

    okno = ModerniPrehravac()
    okno.show()
    
    try:
        sys.exit(app.exec())
    finally:
        pygame.quit()