import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import json
import threading
import sys
from pathlib import Path
from datetime import datetime
import queue
import warnings
import subprocess

def setup_environment():
    """Configura FFmpeg y VLC automáticamente"""
    
    print("⚙️  Configurando entorno...")
    
    # 1. CONFIGURAR FFMPEG
    print("\n🔧 Configurando FFmpeg...")
    
    # Rutas comunes de FFmpeg
    ffmpeg_paths = [
        # Chocolatey
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg.exe",
        # Instalación manual
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        # En PATH del sistema
        None  # pydub lo buscará automáticamente
    ]
    
    ffmpeg_configured = False
    
    for ffmpeg_path in ffmpeg_paths:
        if ffmpeg_path is None:
            # Probar si ffmpeg está en PATH
            try:
                result = subprocess.run(['where', 'ffmpeg'], 
                                      capture_output=True, text=True, shell=True)
                if result.returncode == 0:
                    print("✅ FFmpeg encontrado en PATH del sistema")
                    ffmpeg_configured = True
                    break
            except:
                continue
        
        elif os.path.exists(ffmpeg_path):
            print(f"✅ FFmpeg encontrado en: {ffmpeg_path}")
            
            # Añadir al PATH de esta sesión
            ffmpeg_dir = os.path.dirname(ffmpeg_path)
            if ffmpeg_dir not in os.environ['PATH']:
                os.environ['PATH'] = ffmpeg_dir + ';' + os.environ['PATH']
            
            # Configurar pydub
            try:
                from pydub import AudioSegment
                AudioSegment.converter = ffmpeg_path
                
                # Configurar ffprobe
                ffprobe_path = ffmpeg_path.replace("ffmpeg.exe", "ffprobe.exe")
                if os.path.exists(ffprobe_path):
                    AudioSegment.ffprobe = ffprobe_path
                else:
                    # Intentar encontrar ffprobe en la misma carpeta
                    ffprobe_alt = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")
                    if os.path.exists(ffprobe_alt):
                        AudioSegment.ffprobe = ffprobe_alt
                
                print("✅ Pydub configurado con FFmpeg")
                ffmpeg_configured = True
                break
                
            except ImportError:
                print("⚠️  Pydub no está instalado")
            except Exception as e:
                print(f"⚠️  Error configurando pydub: {e}")
    
    if not ffmpeg_configured:
        print("❌ FFmpeg no encontrado. La conversión de audio no funcionará.")
        print("   Instala con PowerShell (Admin): choco install ffmpeg -y")
        print("   O descarga manualmente de: https://github.com/BtbN/FFmpeg-Builds/releases")
    
    # 2. CONFIGURAR VLC
    print("\n🔧 Configurando VLC...")
    
    vlc_paths = [
        r"C:\Program Files\VideoLAN\VLC",
        r"C:\Program Files (x86)\VideoLAN\VLC",
        r"C:\vlc"
    ]
    
    vlc_configured = False
    
    for vlc_path in vlc_paths:
        if os.path.exists(vlc_path):
            print(f"✅ VLC encontrado en: {vlc_path}")
            
            # Añadir al PATH
            if vlc_path not in os.environ['PATH']:
                os.environ['PATH'] = vlc_path + ';' + os.environ['PATH']
            
            # Configurar variable de entorno para python-vlc
            os.environ['VLC_PLUGIN_PATH'] = os.path.join(vlc_path, 'plugins')
            
            vlc_configured = True
            break
    
    if not vlc_configured:
        print("❌ VLC no encontrado. El reproductor no funcionará.")
        print("   Descarga de: https://www.videolan.org/vlc/")
    
    print("\n" + "="*50)
    print("CONFIGURACIÓN COMPLETADA")
    print("="*50)
    
    return ffmpeg_configured, vlc_configured

# Ejecutar configuración al importar
ffmpeg_ok, vlc_ok = setup_environment()

# Importaciones de bibliotecas externas (instalar con pip)
try:
    from pytube import YouTube
    from pytube.exceptions import VideoUnavailable, RegexMatchError
    from pydub import AudioSegment
    from pydub.exceptions import CouldntDecodeError
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, APIC
    from mutagen.mp3 import MP3
    from PIL import Image, ImageTk
    import vlc
    import yt_dlp as youtube_dl
except ImportError as e:
    print(f"Error: {e}. Por favor, instala las dependencias necesarias.")
    print("Ejecuta: pip install pytube pydub mutagen Pillow python-vlc yt-dlp")
    sys.exit(1)

# Configuración de la aplicación
class Config:
    def __init__(self):
        self.config_file = "config.json"
        self.default_config = {
            "theme": "dark",
            "background": "dark",
            "custom_background": "",
            "download_path": "downloads",
            "default_format": "mp3",
            "bitrate": "128k",
            "volume": 70,
            "recent_collections": [],
            "window_size": "800x600"
        }
        self.load_config()
        
    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        else:
            self.data = self.default_config.copy()
            self.save_config()
    
    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4)
    
    def get(self, key, default=None):
        return self.data.get(key, default)
    
    def set(self, key, value):
        self.data[key] = value
        self.save_config()

# Clase principal de la aplicación
class AudioManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Audio Manager")
        self.root.geometry("800x600")
        
        # Configuración
        self.config = Config()
        self.setup_directories()
        
        # Variables de estado
        self.current_playing = None
        self.current_position = 0
        self.playlist = []
        self.current_index = -1
        self.is_playing = False
        self.is_paused = False
        self.volume = self.config.get("volume", 70) / 100
        
        # Reproductor VLC
        self.vlc_instance = vlc.Instance()
        self.player = self.vlc_instance.media_player_new()
        
        # Cola de mensajes entre hilos
        self.message_queue = queue.Queue()
        
        # Interfaz
        self.setup_ui()
        self.apply_theme()
        
        # Verificar mensajes en la cola periódicamente
        self.check_queue()
        
        # Cargar colecciones recientes
        self.load_recent_collections()
    
    def setup_directories(self):
        """Crea las carpetas necesarias para la aplicación"""
        directories = ["downloads", "collections", "temp", "assets/backgrounds"]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
    
    def setup_ui(self):
        """Configura la interfaz de usuario"""
        # Configurar grid
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        
        # Barra de menú
        self.setup_menu()
        
        # Frame principal
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)
        
        # Notebook (pestañas)
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        
        # Pestaña 1: Descarga de audio
        self.setup_download_tab()
        
        # Pestaña 2: Biblioteca de audio
        self.setup_library_tab()
        
        # Pestaña 3: Colecciones
        self.setup_collections_tab()
        
        # Pestaña 4: Reproductor
        self.setup_player_tab()
        
        # Barra de estado
        self.status_bar = ttk.Label(self.root, text="Listo", relief=tk.SUNKEN)
        self.status_bar.grid(row=2, column=0, sticky="ew", padx=5, pady=2)
        
        # Barra de control del reproductor (fija en la parte inferior)
        self.setup_player_controls()
    
    def setup_menu(self):
        """Configura la barra de menú"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # Menú Archivo
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Archivo", menu=file_menu)
        file_menu.add_command(label="Abrir archivo de audio", command=self.open_audio_file)
        file_menu.add_command(label="Abrir carpeta de descargas", command=self.open_downloads_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self.root.quit)
        
        # Menú Configuración
        config_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Configuración", menu=config_menu)
        
        # Submenú Tema de fondo
        bg_menu = tk.Menu(config_menu, tearoff=0)
        config_menu.add_cascade(label="Tema de fondo", menu=bg_menu)
        bg_menu.add_command(label="Oscuro", command=lambda: self.change_background("dark"))
        bg_menu.add_command(label="Claro", command=lambda: self.change_background("light"))
        bg_menu.add_command(label="Personalizado", command=self.custom_background)
        
        config_menu.add_separator()
        config_menu.add_command(label="Preferencias de descarga", command=self.download_preferences)
    
    def setup_download_tab(self):
        """Configura la pestaña de descarga"""
        self.download_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.download_frame, text="Descargar Audio")
        
        # URL de YouTube
        ttk.Label(self.download_frame, text="URL de YouTube:").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 5))
        self.url_entry = ttk.Entry(self.download_frame, width=60)
        self.url_entry.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        
        # Botón de pegar
        ttk.Button(self.download_frame, text="Pegar", command=self.paste_from_clipboard).grid(row=1, column=2, padx=(0, 10), pady=(0, 10))
        
        # Información del video
        self.video_info_frame = ttk.LabelFrame(self.download_frame, text="Información del Video")
        self.video_info_frame.grid(row=2, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        
        self.video_title_label = ttk.Label(self.video_info_frame, text="Título: No disponible")
        self.video_title_label.grid(row=0, column=0, sticky="w", padx=10, pady=5)
        
        self.video_duration_label = ttk.Label(self.video_info_frame, text="Duración: No disponible")
        self.video_duration_label.grid(row=1, column=0, sticky="w", padx=10, pady=5)
        
        # Opciones de formato
        format_frame = ttk.LabelFrame(self.download_frame, text="Opciones de Formato")
        format_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        
        ttk.Label(format_frame, text="Formato:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        self.format_var = tk.StringVar(value=self.config.get("default_format", "mp3"))
        format_combo = ttk.Combobox(format_frame, textvariable=self.format_var, values=["mp3", "wav", "m4a", "ogg"], state="readonly", width=10)
        format_combo.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        
        ttk.Label(format_frame, text="Calidad (kbps):").grid(row=0, column=2, sticky="w", padx=10, pady=5)
        self.bitrate_var = tk.StringVar(value=self.config.get("bitrate", "128k"))
        bitrate_combo = ttk.Combobox(format_frame, textvariable=self.bitrate_var, values=["64k", "96k", "128k", "192k", "256k", "320k"], state="readonly", width=10)
        bitrate_combo.grid(row=0, column=3, sticky="w", padx=10, pady=5)
        
        # Botones de acción
        button_frame = ttk.Frame(self.download_frame)
        button_frame.grid(row=4, column=0, columnspan=3, padx=10, pady=20)
        
        ttk.Button(button_frame, text="Obtener Información", command=self.get_video_info).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Descargar y Convertir", command=self.download_and_convert).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Limpiar", command=self.clear_download_fields).pack(side=tk.LEFT, padx=5)
        
        # Barra de progreso
        self.progress_bar = ttk.Progressbar(self.download_frame, mode='indeterminate')
        self.progress_bar.grid(row=5, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        
        # Log de descargas
        self.download_log = scrolledtext.ScrolledText(self.download_frame, height=8, state=tk.DISABLED)
        self.download_log.grid(row=6, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="nsew")
        
        # Configurar grid weights
        self.download_frame.grid_rowconfigure(6, weight=1)
        self.download_frame.grid_columnconfigure(0, weight=1)
    
    def setup_library_tab(self):
        """Configura la pestaña de biblioteca de audio"""
        self.library_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.library_frame, text="Biblioteca")
        
        # Panel de búsqueda y filtros
        search_frame = ttk.Frame(self.library_frame)
        search_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(search_frame, text="Buscar:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_entry = ttk.Entry(search_frame, width=40)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", self.search_audio_files)
        
        ttk.Button(search_frame, text="Explorar", command=self.browse_audio_files).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(search_frame, text="Actualizar", command=self.load_audio_files).pack(side=tk.LEFT)
        
        # Lista de archivos de audio
        columns = ("#", "Nombre", "Duración", "Tamaño", "Formato", "Ruta")
        self.audio_tree = ttk.Treeview(self.library_frame, columns=columns, show="headings", height=15)
        
        for col in columns:
            self.audio_tree.heading(col, text=col)
            self.audio_tree.column(col, width=100)
        
        self.audio_tree.column("#", width=50)
        self.audio_tree.column("Nombre", width=200)
        self.audio_tree.column("Ruta", width=300)
        
        # Scrollbar para la lista
        scrollbar = ttk.Scrollbar(self.library_frame, orient=tk.VERTICAL, command=self.audio_tree.yview)
        self.audio_tree.configure(yscrollcommand=scrollbar.set)
        
        # Empaquetar Treeview y Scrollbar
        self.audio_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=(0, 10))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=(0, 10))
        
        # Panel de controles para la biblioteca
        control_frame = ttk.Frame(self.library_frame)
        control_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(control_frame, text="Reproducir", command=self.play_selected_audio).pack(side=tk.LEFT, padx=2)
        ttk.Button(control_frame, text="Añadir a Cola", command=self.add_to_queue).pack(side=tk.LEFT, padx=2)
        ttk.Button(control_frame, text="Añadir a Colección", command=self.add_to_collection).pack(side=tk.LEFT, padx=2)
        ttk.Button(control_frame, text="Eliminar", command=self.delete_audio_file).pack(side=tk.LEFT, padx=2)
    
    def setup_collections_tab(self):
        """Configura la pestaña de colecciones"""
        self.collections_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.collections_frame, text="Colecciones")
        
        # Panel para crear/administrar colecciones
        manage_frame = ttk.LabelFrame(self.collections_frame, text="Administrar Colecciones")
        manage_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(manage_frame, text="Nombre:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.collection_name_entry = ttk.Entry(manage_frame, width=30)
        self.collection_name_entry.grid(row=0, column=1, padx=10, pady=10, sticky="w")
        
        ttk.Button(manage_frame, text="Crear Colección", command=self.create_collection).grid(row=0, column=2, padx=10, pady=10)
        ttk.Button(manage_frame, text="Eliminar Colección", command=self.delete_collection).grid(row=0, column=3, padx=10, pady=10)
        
        # Lista de colecciones
        collections_list_frame = ttk.Frame(self.collections_frame)
        collections_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        ttk.Label(collections_list_frame, text="Colecciones:").pack(anchor="w", pady=(0, 5))
        
        self.collections_listbox = tk.Listbox(collections_list_frame, height=10)
        self.collections_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(collections_list_frame, orient=tk.VERTICAL, command=self.collections_listbox.yview)
        self.collections_listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Contenido de la colección seleccionada
        content_frame = ttk.LabelFrame(self.collections_frame, text="Contenido de la Colección")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        columns = ("Nombre", "Duración", "Formato")
        self.collection_tree = ttk.Treeview(content_frame, columns=columns, show="headings", height=8)
        
        for col in columns:
            self.collection_tree.heading(col, text=col)
            self.collection_tree.column(col, width=150)
        
        scrollbar2 = ttk.Scrollbar(content_frame, orient=tk.VERTICAL, command=self.collection_tree.yview)
        self.collection_tree.configure(yscrollcommand=scrollbar2.set)
        
        self.collection_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar2.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Conectar eventos
        self.collections_listbox.bind("<<ListboxSelect>>", self.load_collection_content)
    
    def setup_player_tab(self):
        """Configura la pestaña del reproductor"""
        self.player_tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.player_tab_frame, text="Reproductor")
        
        # Información de la canción actual
        info_frame = ttk.LabelFrame(self.player_tab_frame, text="Ahora Suena")
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.current_song_label = ttk.Label(info_frame, text="No hay ninguna canción en reproducción", font=("Arial", 12, "bold"))
        self.current_song_label.pack(pady=10)
        
        self.current_artist_label = ttk.Label(info_frame, text="")
        self.current_artist_label.pack()
        
        # Visualización de la cola de reproducción
        queue_frame = ttk.LabelFrame(self.player_tab_frame, text="Cola de Reproducción")
        queue_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        columns = ("#", "Nombre", "Duración")
        self.queue_tree = ttk.Treeview(queue_frame, columns=columns, show="headings", height=10)
        
        for col in columns:
            self.queue_tree.heading(col, text=col)
        
        self.queue_tree.column("#", width=50)
        self.queue_tree.column("Nombre", width=300)
        self.queue_tree.column("Duración", width=100)
        
        scrollbar = ttk.Scrollbar(queue_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=scrollbar.set)
        
        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Controles de la cola
        queue_controls = ttk.Frame(queue_frame)
        queue_controls.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(queue_controls, text="Subir", command=self.move_up_in_queue).pack(side=tk.LEFT, padx=2)
        ttk.Button(queue_controls, text="Bajar", command=self.move_down_in_queue).pack(side=tk.LEFT, padx=2)
        ttk.Button(queue_controls, text="Eliminar", command=self.remove_from_queue).pack(side=tk.LEFT, padx=2)
        ttk.Button(queue_controls, text="Limpiar Cola", command=self.clear_queue).pack(side=tk.LEFT, padx=2)
    
    def setup_player_controls(self):
        """Configura los controles del reproductor (barra inferior fija)"""
        control_frame = ttk.Frame(self.root, relief=tk.RAISED, borderwidth=1)
        control_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        
        # Botones de control
        ttk.Button(control_frame, text="⏮", width=3, command=self.previous_track).pack(side=tk.LEFT, padx=2)
        self.play_button = ttk.Button(control_frame, text="▶", width=3, command=self.toggle_play)
        self.play_button.pack(side=tk.LEFT, padx=2)
        ttk.Button(control_frame, text="⏭", width=3, command=self.next_track).pack(side=tk.LEFT, padx=2)
        
        # Barra de progreso
        self.progress_scale = ttk.Scale(control_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=self.seek_track)
        self.progress_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        # Etiqueta de tiempo
        self.time_label = ttk.Label(control_frame, text="00:00 / 00:00")
        self.time_label.pack(side=tk.LEFT, padx=5)
        
        # Control de volumen
        ttk.Label(control_frame, text="Vol:").pack(side=tk.LEFT, padx=(10, 0))
        self.volume_scale = ttk.Scale(control_frame, from_=0, to=100, orient=tk.HORIZONTAL, 
                                      value=self.config.get("volume", 70), command=self.change_volume, length=100)
        self.volume_scale.pack(side=tk.LEFT, padx=5)
        
        # Actualizar la barra de progreso periódicamente
        self.update_progress()
    
    def apply_theme(self):
        """Aplica el tema seleccionado"""
        theme = self.config.get("background", "dark")
        
        if theme == "dark":
            self.root.configure(bg="#2e2e2e")
            style = ttk.Style()
            style.theme_use('clam')
            
            # Configurar colores oscuros
            style.configure("TLabel", background="#2e2e2e", foreground="white")
            style.configure("TFrame", background="#2e2e2e")
            style.configure("TLabelframe", background="#2e2e2e", foreground="white")
            style.configure("TLabelframe.Label", background="#2e2e2e", foreground="white")
            style.configure("TButton", background="#3e3e3e", foreground="white")
            style.configure("TEntry", fieldbackground="#3e3e3e", foreground="white")
            style.configure("TCombobox", fieldbackground="#3e3e3e", foreground="white")
            style.configure("Treeview", background="#3e3e3e", foreground="white", fieldbackground="#3e3e3e")
            style.configure("Treeview.Heading", background="#2e2e2e", foreground="white")
            style.map("Treeview", background=[("selected", "#4e4e4e")])
            
        elif theme == "light":
            self.root.configure(bg="#f0f0f0")
            style = ttk.Style()
            style.theme_use('clam')
            
            # Configurar colores claros
            style.configure("TLabel", background="#f0f0f0", foreground="black")
            style.configure("TFrame", background="#f0f0f0")
            style.configure("TLabelframe", background="#f0f0f0", foreground="black")
            style.configure("TLabelframe.Label", background="#f0f0f0", foreground="black")
            style.configure("TButton", background="#e0e0e0", foreground="black")
            style.configure("TEntry", fieldbackground="white", foreground="black")
            style.configure("TCombobox", fieldbackground="white", foreground="black")
            style.configure("Treeview", background="white", foreground="black", fieldbackground="white")
            style.configure("Treeview.Heading", background="#e0e0e0", foreground="black")
            style.map("Treeview", background=[("selected", "#d0d0d0")])
        
        # Fondo personalizado
        custom_bg = self.config.get("custom_background", "")
        if custom_bg and os.path.exists(custom_bg):
            try:
                bg_image = Image.open(custom_bg)
                bg_photo = ImageTk.PhotoImage(bg_image)
                bg_label = tk.Label(self.root, image=bg_photo)
                bg_label.image = bg_photo  # Mantener referencia
                bg_label.place(x=0, y=0, relwidth=1, relheight=1)
            except Exception as e:
                print(f"Error al cargar fondo personalizado: {e}")
    
    # Funciones de utilidad
    def check_queue(self):
        """Verifica mensajes en la cola desde otros hilos"""
        try:
            while True:
                message = self.message_queue.get_nowait()
                if message[0] == "log":
                    self.log_message(message[1])
                elif message[0] == "progress_start":
                    self.progress_bar.start()
                elif message[0] == "progress_stop":
                    self.progress_bar.stop()
                elif message[0] == "video_info":
                    self.update_video_info(message[1])
                elif message[0] == "download_complete":
                    self.on_download_complete(message[1])
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.check_queue)
    
    def log_message(self, message):
        """Añade un mensaje al log de descargas"""
        self.download_log.config(state=tk.NORMAL)
        self.download_log.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {message}\n")
        self.download_log.see(tk.END)
        self.download_log.config(state=tk.DISABLED)
    
    def update_status(self, message):
        """Actualiza la barra de estado"""
        self.status_bar.config(text=message)
    
    # Funciones del menú y configuración
    def change_background(self, theme):
        """Cambia el tema de fondo"""
        self.config.set("background", theme)
        if theme != "custom":
            self.config.set("custom_background", "")
        self.apply_theme()
    
    def custom_background(self):
        """Permite seleccionar un fondo personalizado"""
        file_path = filedialog.askopenfilename(
            title="Seleccionar imagen de fondo",
            filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.gif *.bmp")]
        )
        
        if file_path:
            self.config.set("background", "custom")
            self.config.set("custom_background", file_path)
            self.apply_theme()
    
    def download_preferences(self):
        """Muestra el diálogo de preferencias de descarga"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Preferencias de Descarga")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Carpeta de descargas:").pack(anchor="w", padx=20, pady=(20, 5))
        
        path_frame = ttk.Frame(dialog)
        path_frame.pack(fill=tk.X, padx=20, pady=5)
        
        current_path = self.config.get("download_path", "downloads")
        path_var = tk.StringVar(value=current_path)
        path_entry = ttk.Entry(path_frame, textvariable=path_var)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        def browse_path():
            folder = filedialog.askdirectory(initialdir=current_path)
            if folder:
                path_var.set(folder)
        
        ttk.Button(path_frame, text="Examinar", command=browse_path).pack(side=tk.RIGHT, padx=(5, 0))
        
        ttk.Label(dialog, text="Formato predeterminado:").pack(anchor="w", padx=20, pady=(10, 5))
        default_format = tk.StringVar(value=self.config.get("default_format", "mp3"))
        ttk.Combobox(dialog, textvariable=default_format, values=["mp3", "wav", "m4a", "ogg"], state="readonly").pack(anchor="w", padx=20, pady=5)
        
        ttk.Label(dialog, text="Calidad predeterminada (kbps):").pack(anchor="w", padx=20, pady=(10, 5))
        default_bitrate = tk.StringVar(value=self.config.get("bitrate", "128k"))
        ttk.Combobox(dialog, textvariable=default_bitrate, values=["64k", "96k", "128k", "192k", "256k", "320k"], state="readonly").pack(anchor="w", padx=20, pady=5)
        
        def save_preferences():
            self.config.set("download_path", path_var.get())
            self.config.set("default_format", default_format.get())
            self.config.set("bitrate", default_bitrate.get())
            dialog.destroy()
            messagebox.showinfo("Preferencias", "Preferencias guardadas correctamente.")
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side=tk.BOTTOM, pady=20)
        
        ttk.Button(button_frame, text="Guardar", command=save_preferences).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Cancelar", command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    # Funciones de la pestaña de descarga
    def paste_from_clipboard(self):
        """Pega el contenido del portapapeles en el campo de URL"""
        try:
            clipboard_content = self.root.clipboard_get()
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, clipboard_content)
        except:
            pass
    
    def get_video_info(self):
        """Obtiene información del video de YouTube"""
        url = self.url_entry.get().strip()
        
        if not url:
            messagebox.showwarning("Advertencia", "Por favor, introduce una URL de YouTube.")
            return
        
        # Ejecutar en un hilo separado para no bloquear la interfaz
        threading.Thread(target=self._get_video_info_thread, args=(url,), daemon=True).start()
    
    def _get_video_info_thread(self, url):
        """Hilo para obtener información del video"""
        self.message_queue.put(("progress_start",))
        self.message_queue.put(("log", f"Obteniendo información para: {url}"))
        
        try:
            yt = YouTube(url)
            
            # Extraer información
            info = {
                "title": yt.title,
                "duration": str(yt.length // 60) + ":" + str(yt.length % 60).zfill(2),
                "author": yt.author,
                "views": yt.views,
                "publish_date": yt.publish_date.strftime("%Y-%m-%d") if yt.publish_date else "Desconocido"
            }
            
            self.message_queue.put(("video_info", info))
            self.message_queue.put(("log", f"Información obtenida: {info['title']}"))
            
        except VideoUnavailable:
            self.message_queue.put(("log", "Error: Video no disponible"))
            messagebox.showerror("Error", "El video no está disponible.")
        except RegexMatchError:
            self.message_queue.put(("log", "Error: URL no válida"))
            messagebox.showerror("Error", "La URL de YouTube no es válida.")
        except Exception as e:
            self.message_queue.put(("log", f"Error: {str(e)}"))
            messagebox.showerror("Error", f"Ocurrió un error: {str(e)}")
        finally:
            self.message_queue.put(("progress_stop",))
    
    def update_video_info(self, info):
        """Actualiza la información del video en la interfaz"""
        self.video_title_label.config(text=f"Título: {info['title']}")
        self.video_duration_label.config(text=f"Duración: {info['duration']}")
    
    def download_and_convert(self):
        """Descarga y convierte el video de YouTube"""
        url = self.url_entry.get().strip()
        
        if not url:
            messagebox.showwarning("Advertencia", "Por favor, introduce una URL de YouTube.")
            return
        
        # Ejecutar en un hilo separado
        threading.Thread(target=self._download_and_convert_thread, args=(url,), daemon=True).start()
    
    def _download_and_convert_thread(self, url):
        """Hilo para descargar y convertir el video"""
        self.message_queue.put(("progress_start",))
        self.message_queue.put(("log", f"Iniciando descarga: {url}"))
        
        try:
            # Configurar opciones de yt-dlp
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': 'temp/%(title)s.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [self.download_progress_hook],
            }
            
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                audio_file = ydl.prepare_filename(info_dict)
                
                # Convertir al formato deseado
                output_format = self.format_var.get()
                output_path = self.config.get("download_path", "downloads")
                
                # Crear nombre de archivo seguro
                safe_title = "".join(c for c in info_dict['title'] if c.isalnum() or c in (' ', '-', '_')).rstrip()
                output_file = os.path.join(output_path, f"{safe_title}.{output_format}")
                
                # Convertir usando pydub
                self.message_queue.put(("log", f"Convirtiendo a {output_format}..."))
                
                audio = AudioSegment.from_file(audio_file)
                
                # Aplicar configuración de calidad
                bitrate = self.bitrate_var.get()
                
                # Exportar al formato deseado
                if output_format == "mp3":
                    audio.export(output_file, format="mp3", bitrate=bitrate)
                else:
                    audio.export(output_file, format=output_format)
                
                # Limpiar archivo temporal
                os.remove(audio_file)
                
                self.message_queue.put(("log", f"Conversión completada: {output_file}"))
                self.message_queue.put(("download_complete", output_file))
                
        except Exception as e:
            self.message_queue.put(("log", f"Error: {str(e)}"))
            messagebox.showerror("Error", f"Ocurrió un error: {str(e)}")
        finally:
            self.message_queue.put(("progress_stop",))
    
    def download_progress_hook(self, d):
        """Hook para el progreso de descarga"""
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '0%').strip()
            self.message_queue.put(("log", f"Descargando: {percent}"))
        elif d['status'] == 'finished':
            self.message_queue.put(("log", "Descarga completada, convirtiendo..."))
    
    def on_download_complete(self, file_path):
        """Maneja la finalización de la descarga"""
        messagebox.showinfo("Éxito", f"Audio descargado y convertido:\n{file_path}")
        self.load_audio_files()  # Actualizar la biblioteca
    
    def clear_download_fields(self):
        """Limpia los campos de descarga"""
        self.url_entry.delete(0, tk.END)
        self.video_title_label.config(text="Título: No disponible")
        self.video_duration_label.config(text="Duración: No disponible")
        self.download_log.config(state=tk.NORMAL)
        self.download_log.delete(1.0, tk.END)
        self.download_log.config(state=tk.DISABLED)
    
    # Funciones de la pestaña de biblioteca
    def load_audio_files(self):
        """Carga los archivos de audio de la carpeta de descargas"""
        # Limpiar lista actual
        for item in self.audio_tree.get_children():
            self.audio_tree.delete(item)
        
        # Obtener archivos de audio
        download_path = self.config.get("download_path", "downloads")
        audio_extensions = ('.mp3', '.wav', '.m4a', '.ogg', '.flac')
        
        if os.path.exists(download_path):
            for i, filename in enumerate(os.listdir(download_path), 1):
                if filename.lower().endswith(audio_extensions):
                    filepath = os.path.join(download_path, filename)
                    size = os.path.getsize(filepath) / (1024 * 1024)  # MB
                    
                    # Obtener duración si es posible
                    duration = "Desconocida"
                    try:
                        audio = MP3(filepath)
                        duration_sec = audio.info.length
                        duration = f"{int(duration_sec // 60)}:{int(duration_sec % 60):02d}"
                    except:
                        pass
                    
                    # Añadir a la lista
                    self.audio_tree.insert("", tk.END, values=(
                        i, filename, duration, f"{size:.2f} MB", 
                        os.path.splitext(filename)[1][1:].upper(), filepath
                    ))
        
        self.update_status(f"Biblioteca cargada: {download_path}")
    
    def search_audio_files(self, event=None):
        """Busca archivos de audio en la biblioteca"""
        query = self.search_entry.get().lower()
        
        for item in self.audio_tree.get_children():
            values = self.audio_tree.item(item, "values")
            if query in values[1].lower():  # Buscar en el nombre
                self.audio_tree.selection_set(item)
                self.audio_tree.see(item)
                break
    
    def browse_audio_files(self):
        """Permite explorar y añadir archivos de audio desde cualquier ubicación"""
        files = filedialog.askopenfilenames(
            title="Seleccionar archivos de audio",
            filetypes=[("Archivos de audio", "*.mp3 *.wav *.m4a *.ogg *.flac")]
        )
        
        if files:
            download_path = self.config.get("download_path", "downloads")
            for file in files:
                # Copiar archivo a la carpeta de descargas
                import shutil
                filename = os.path.basename(file)
                dest = os.path.join(download_path, filename)
                
                # Si el archivo ya existe, añadir un sufijo
                counter = 1
                while os.path.exists(dest):
                    name, ext = os.path.splitext(filename)
                    dest = os.path.join(download_path, f"{name}_{counter}{ext}")
                    counter += 1
                
                shutil.copy2(file, dest)
                self.log_message(f"Archivo añadido: {filename}")
            
            self.load_audio_files()
    
    def play_selected_audio(self):
        """Reproduce el archivo de audio seleccionado"""
        selection = self.audio_tree.selection()
        if not selection:
            messagebox.showwarning("Advertencia", "Por favor, selecciona un archivo de audio.")
            return
        
        item = selection[0]
        values = self.audio_tree.item(item, "values")
        filepath = values[5]  # La ruta está en la columna 6
        
        self.play_audio(filepath)
    
    def play_audio(self, filepath):
        """Reproduce un archivo de audio"""
        try:
            # Detener reproducción actual
            if self.is_playing:
                self.player.stop()
            
            # Configurar y reproducir
            media = self.vlc_instance.media_new(filepath)
            self.player.set_media(media)
            self.player.play()
            self.player.audio_set_volume(int(self.volume * 100))
            
            # Actualizar estado
            self.current_playing = filepath
            self.is_playing = True
            self.is_paused = False
            
            # Actualizar interfaz
            filename = os.path.basename(filepath)
            self.current_song_label.config(text=filename)
            self.play_button.config(text="⏸")
            
            # Actualizar tiempo de la canción
            self.update_song_duration()
            
            self.update_status(f"Reproduciendo: {filename}")
            
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo reproducir el archivo: {str(e)}")
    
    def add_to_queue(self):
        """Añade el archivo seleccionado a la cola de reproducción"""
        selection = self.audio_tree.selection()
        if not selection:
            messagebox.showwarning("Advertencia", "Por favor, selecciona un archivo de audio.")
            return
        
        item = selection[0]
        values = self.audio_tree.item(item, "values")
        filepath = values[5]
        filename = values[1]
        
        # Obtener duración
        duration = values[2]
        
        # Añadir a la cola
        self.playlist.append(filepath)
        self.queue_tree.insert("", tk.END, values=(len(self.playlist), filename, duration))
        
        self.update_status(f"Añadido a la cola: {filename}")
    
    def add_to_collection(self):
        """Añade el archivo seleccionado a una colección"""
        selection = self.audio_tree.selection()
        if not selection:
            messagebox.showwarning("Advertencia", "Por favor, selecciona un archivo de audio.")
            return
        
        # Obtener colecciones disponibles
        collections = []
        collections_path = "collections"
        if os.path.exists(collections_path):
            collections = [f for f in os.listdir(collections_path) if f.endswith('.json')]
        
        if not collections:
            messagebox.showwarning("Advertencia", "No hay colecciones disponibles. Crea una colección primero.")
            return
        
        # Diálogo para seleccionar colección
        dialog = tk.Toplevel(self.root)
        dialog.title("Seleccionar Colección")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Selecciona una colección:").pack(pady=20)
        
        collection_var = tk.StringVar()
        collection_combo = ttk.Combobox(dialog, textvariable=collection_var, values=[c.replace('.json', '') for c in collections], state="readonly")
        collection_combo.pack(pady=10)
        
        def add_to_selected():
            collection_name = collection_var.get()
            if not collection_name:
                messagebox.showwarning("Advertencia", "Por favor, selecciona una colección.")
                return
            
            item = selection[0]
            values = self.audio_tree.item(item, "values")
            filepath = values[5]
            filename = values[1]
            
            # Añadir a la colección
            collection_file = os.path.join(collections_path, f"{collection_name}.json")
            if os.path.exists(collection_file):
                with open(collection_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {"name": collection_name, "files": []}
            
            # Verificar si ya existe
            if filepath not in data["files"]:
                data["files"].append(filepath)
                
                with open(collection_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
                
                messagebox.showinfo("Éxito", f"Archivo añadido a la colección '{collection_name}'.")
            else:
                messagebox.showinfo("Información", "El archivo ya está en esta colección.")
            
            dialog.destroy()
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side=tk.BOTTOM, pady=20)
        
        ttk.Button(button_frame, text="Añadir", command=add_to_selected).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Cancelar", command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def delete_audio_file(self):
        """Elimina el archivo de audio seleccionado"""
        selection = self.audio_tree.selection()
        if not selection:
            messagebox.showwarning("Advertencia", "Por favor, selecciona un archivo de audio.")
            return
        
        item = selection[0]
        values = self.audio_tree.item(item, "values")
        filepath = values[5]
        filename = values[1]
        
        # Confirmar eliminación
        if messagebox.askyesno("Confirmar", f"¿Estás seguro de que quieres eliminar '{filename}'?"):
            try:
                os.remove(filepath)
                self.audio_tree.delete(item)
                self.update_status(f"Archivo eliminado: {filename}")
                
                # Si estaba en reproducción, detener
                if self.current_playing == filepath:
                    self.player.stop()
                    self.current_playing = None
                    self.is_playing = False
                    self.play_button.config(text="▶")
                    self.current_song_label.config(text="No hay ninguna canción en reproducción")
                
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el archivo: {str(e)}")
    
    # Funciones de la pestaña de colecciones
    def load_recent_collections(self):
        """Carga las colecciones recientes"""
        collections_path = "collections"
        if os.path.exists(collections_path):
            collections = [f.replace('.json', '') for f in os.listdir(collections_path) if f.endswith('.json')]
            for collection in collections:
                self.collections_listbox.insert(tk.END, collection)
    
    def create_collection(self):
        """Crea una nueva colección"""
        name = self.collection_name_entry.get().strip()
        
        if not name:
            messagebox.showwarning("Advertencia", "Por favor, introduce un nombre para la colección.")
            return
        
        # Verificar si ya existe
        collection_file = os.path.join("collections", f"{name}.json")
        if os.path.exists(collection_file):
            messagebox.showwarning("Advertencia", f"La colección '{name}' ya existe.")
            return
        
        # Crear colección vacía
        data = {"name": name, "files": [], "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        
        with open(collection_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        
        # Actualizar lista
        self.collections_listbox.insert(tk.END, name)
        self.collection_name_entry.delete(0, tk.END)
        
        self.update_status(f"Colección creada: {name}")
    
    def delete_collection(self):
        """Elimina la colección seleccionada"""
        selection = self.collections_listbox.curselection()
        if not selection:
            messagebox.showwarning("Advertencia", "Por favor, selecciona una colección.")
            return
        
        name = self.collections_listbox.get(selection[0])
        
        # Confirmar eliminación
        if messagebox.askyesno("Confirmar", f"¿Estás seguro de que quieres eliminar la colección '{name}'?"):
            collection_file = os.path.join("collections", f"{name}.json")
            
            try:
                os.remove(collection_file)
                self.collections_listbox.delete(selection[0])
                self.collection_tree.delete(*self.collection_tree.get_children())
                
                self.update_status(f"Colección eliminada: {name}")
                
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar la colección: {str(e)}")
    
    def load_collection_content(self, event):
        """Carga el contenido de la colección seleccionada"""
        selection = self.collections_listbox.curselection()
        if not selection:
            return
        
        name = self.collections_listbox.get(selection[0])
        collection_file = os.path.join("collections", f"{name}.json")
        
        # Limpiar lista actual
        self.collection_tree.delete(*self.collection_tree.get_children())
        
        if os.path.exists(collection_file):
            with open(collection_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Mostrar archivos
            for i, filepath in enumerate(data["files"], 1):
                if os.path.exists(filepath):
                    filename = os.path.basename(filepath)
                    
                    # Obtener duración si es posible
                    duration = "Desconocida"
                    try:
                        audio = MP3(filepath)
                        duration_sec = audio.info.length
                        duration = f"{int(duration_sec // 60)}:{int(duration_sec % 60):02d}"
                    except:
                        pass
                    
                    format_ext = os.path.splitext(filename)[1][1:].upper()
                    
                    self.collection_tree.insert("", tk.END, values=(filename, duration, format_ext))
    
    # Funciones del reproductor
    def toggle_play(self):
        """Alterna entre reproducir y pausar"""
        if not self.is_playing:
            # Si hay algo en la cola, reproducir
            if self.playlist:
                self.play_next_in_queue()
            else:
                messagebox.showinfo("Información", "No hay canciones en la cola de reproducción.")
        else:
            if self.is_paused:
                self.player.play()
                self.is_paused = False
                self.play_button.config(text="⏸")
            else:
                self.player.pause()
                self.is_paused = True
                self.play_button.config(text="▶")
    
    def play_next_in_queue(self):
        """Reproduce la siguiente canción en la cola"""
        if not self.playlist:
            return
        
        self.current_index += 1
        if self.current_index >= len(self.playlist):
            self.current_index = 0
        
        next_file = self.playlist[self.current_index]
        self.play_audio(next_file)
        
        # Resaltar en la lista de cola
        for item in self.queue_tree.get_children():
            values = self.queue_tree.item(item, "values")
            if int(values[0]) == self.current_index + 1:
                self.queue_tree.selection_set(item)
                self.queue_tree.see(item)
                break
    
    def previous_track(self):
        """Reproduce la canción anterior"""
        if not self.playlist:
            return
        
        self.current_index -= 1
        if self.current_index < 0:
            self.current_index = len(self.playlist) - 1
        
        prev_file = self.playlist[self.current_index]
        self.play_audio(prev_file)
        
        # Resaltar en la lista de cola
        for item in self.queue_tree.get_children():
            values = self.queue_tree.item(item, "values")
            if int(values[0]) == self.current_index + 1:
                self.queue_tree.selection_set(item)
                self.queue_tree.see(item)
                break
    
    def next_track(self):
        """Reproduce la siguiente canción"""
        self.play_next_in_queue()
    
    def seek_track(self, value):
        """Busca una posición en la canción actual"""
        if self.is_playing and not self.is_paused:
            # Convertir valor de escala a tiempo
            media = self.player.get_media()
            if media:
                media.parse()  # Parsear para obtener duración
                duration = media.get_duration() / 1000  # en segundos
                seek_time = (float(value) / 100) * duration
                self.player.set_time(int(seek_time * 1000))
    
    def change_volume(self, value):
        """Cambia el volumen"""
        self.volume = float(value) / 100
        self.player.audio_set_volume(int(self.volume * 100))
        self.config.set("volume", int(value))
    
    def update_progress(self):
        """Actualiza la barra de progreso y el tiempo"""
        if self.is_playing and not self.is_paused:
            # Obtener tiempo actual y duración
            current_time = self.player.get_time() / 1000  # en segundos
            media = self.player.get_media()
            
            if media:
                media.parse()
                duration = media.get_duration() / 1000  # en segundos
                
                if duration > 0:
                    # Actualizar barra de progreso
                    progress_percent = (current_time / duration) * 100
                    self.progress_scale.set(progress_percent)
                    
                    # Actualizar etiqueta de tiempo
                    current_str = f"{int(current_time // 60)}:{int(current_time % 60):02d}"
                    duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}"
                    self.time_label.config(text=f"{current_str} / {duration_str}")
            
            # Verificar si la canción ha terminado
            state = self.player.get_state()
            if state == vlc.State.Ended:
                self.is_playing = False
                self.play_next_in_queue()
        
        # Programar próxima actualización
        self.root.after(1000, self.update_progress)
    
    def update_song_duration(self):
        """Actualiza la duración de la canción actual"""
        if self.is_playing:
            media = self.player.get_media()
            if media:
                media.parse()
                duration = media.get_duration() / 1000  # en segundos
                if duration > 0:
                    duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}"
                    self.time_label.config(text=f"00:00 / {duration_str}")
    
    def move_up_in_queue(self):
        """Mueve hacia arriba la canción seleccionada en la cola"""
        selection = self.queue_tree.selection()
        if not selection:
            return
        
        item = selection[0]
        index = self.queue_tree.index(item)
        
        if index > 0:
            # Mover en la lista de reproducción
            self.playlist[index], self.playlist[index-1] = self.playlist[index-1], self.playlist[index]
            
            # Actualizar árbol
            values = self.queue_tree.item(item, "values")
            self.queue_tree.delete(item)
            self.queue_tree.insert("", index-1, values=values)
            
            # Actualizar índices
            self.update_queue_indices()
    
    def move_down_in_queue(self):
        """Mueve hacia abajo la canción seleccionada en la cola"""
        selection = self.queue_tree.selection()
        if not selection:
            return
        
        item = selection[0]
        index = self.queue_tree.index(item)
        
        if index < len(self.playlist) - 1:
            # Mover en la lista de reproducción
            self.playlist[index], self.playlist[index+1] = self.playlist[index+1], self.playlist[index]
            
            # Actualizar árbol
            values = self.queue_tree.item(item, "values")
            self.queue_tree.delete(item)
            self.queue_tree.insert("", index+1, values=values)
            
            # Actualizar índices
            self.update_queue_indices()
    
    def remove_from_queue(self):
        """Elimina la canción seleccionada de la cola"""
        selection = self.queue_tree.selection()
        if not selection:
            return
        
        item = selection[0]
        index = self.queue_tree.index(item)
        
        # Eliminar de la lista de reproducción
        if index < len(self.playlist):
            removed_file = self.playlist.pop(index)
            
            # Si era la canción actual, reproducir la siguiente
            if self.current_playing == removed_file:
                self.player.stop()
                self.play_next_in_queue()
        
        # Eliminar del árbol
        self.queue_tree.delete(item)
        
        # Actualizar índices
        self.update_queue_indices()
    
    def clear_queue(self):
        """Limpia toda la cola de reproducción"""
        if messagebox.askyesno("Confirmar", "¿Estás seguro de que quieres limpiar toda la cola de reproducción?"):
            self.playlist.clear()
            self.queue_tree.delete(*self.queue_tree.get_children())
            self.current_index = -1
            
            # Detener reproducción si está activa
            if self.is_playing:
                self.player.stop()
                self.is_playing = False
                self.play_button.config(text="▶")
                self.current_song_label.config(text="No hay ninguna canción en reproducción")
    
    def update_queue_indices(self):
        """Actualiza los índices en la cola de reproducción"""
        for i, item in enumerate(self.queue_tree.get_children(), 1):
            values = list(self.queue_tree.item(item, "values"))
            values[0] = i
            self.queue_tree.item(item, values=values)
    
    # Funciones auxiliares
    def open_audio_file(self):
        """Abre un archivo de audio para reproducir"""
        filepath = filedialog.askopenfilename(
            title="Seleccionar archivo de audio",
            filetypes=[("Archivos de audio", "*.mp3 *.wav *.m4a *.ogg *.flac")]
        )
        
        if filepath:
            self.play_audio(filepath)
    
    def open_downloads_folder(self):
        """Abre la carpeta de descargas"""
        download_path = self.config.get("download_path", "downloads")
        if os.path.exists(download_path):
            os.startfile(download_path)
        else:
            messagebox.showwarning("Advertencia", f"La carpeta '{download_path}' no existe.")

def main():
    """Función principal"""
    root = tk.Tk()
    app = AudioManagerApp(root)
    
    # Cargar archivos de audio al iniciar
    root.after(100, app.load_audio_files)
    
    # Manejar cierre de ventana
    def on_closing():
        # Detener reproducción
        if app.is_playing:
            app.player.stop()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()