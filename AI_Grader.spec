# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
playwright_datas = collect_data_files('playwright')
playwright_hidden = collect_submodules('playwright')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('models', 'models'),
        ('services', 'services'),
        ('config.py', '.'),
    ] + playwright_datas,
    hiddenimports=[
        'google.genai',
        'google.genai.types',
        'pydantic',
        'openpyxl',
        'flask',
        'statistics',
        'pypdf',
        'playwright.sync_api',
    ] + playwright_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tensorflow', 'torch', 'torchvision', 'torchaudio',
        'scipy', 'numpy', 'pandas', 'matplotlib', 'PIL', 'Pillow',
        'sympy', 'sklearn', 'scikit-learn',
        'pytest', 'IPython', 'notebook', 'jupyter',
        'pyarrow', 'fsspec', 'psutil',
        'tkinter.tix',
        'cv2', 'opencv-python',
        'streamlit', 'gradio',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AI_Grader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AI_Grader',
)
