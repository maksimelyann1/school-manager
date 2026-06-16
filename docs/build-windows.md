# Windows Build

Цей файл описує локальну Windows-збірку School Manager.

## Потрібно встановити

- Windows 10/11.
- Python 3.12.
- Node.js 20.
- Inno Setup 6.
- Git.

## Підготовка залежностей

```powershell
cd "D:\Logika\school_manager codex"

python -m pip install --upgrade pip
pip install -r backend\requirements.txt
pip install pyinstaller

cd frontend
npm ci
cd ..
```

Якщо використовується `backend\venv`, активуй його перед командами Python.

## Збірка frontend

```powershell
cd "D:\Logika\school_manager codex\frontend"
npm run build
cd ..
```

`frontend/dist` має існувати перед PyInstaller.

## Перевірка Python

```powershell
python -m compileall backend desktop_app.py pyinstaller_runtime_hook.py scripts
```

## Portable-збірка

```powershell
pyinstaller SchoolManager.spec --noconfirm --clean
```

Результат:

```text
dist\SchoolManager\SchoolManager.exe
```

Перевірити, що збірка не містить приватних даних:

```powershell
python scripts\check_release_clean.py dist\SchoolManager
```

## Installer

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

Результат:

```text
dist\SchoolManager_Setup.exe
```

Перевірка installer:

```powershell
python scripts\check_release_clean.py dist\SchoolManager_Setup.exe
```

## ZIP portable

```powershell
Compress-Archive -Path dist\SchoolManager -DestinationPath dist\SchoolManager-windows-portable.zip -Force
```

## Швидкий smoke-test

1. Запустити `dist\SchoolManager\SchoolManager.exe`.
2. Перевірити `http://127.0.0.1:8001/health`.
3. Перевірити відкриття головного вікна.
4. Перевірити `Налаштування -> Telegram акаунт`.
5. Перевірити `Налаштування -> Google AI`, якщо потрібна генерація.
6. Перевірити відправку у тестову групу.
7. Перевірити `Звіт батькам`.
8. Закрити програму через tray і переконатися, що backend зупинився.

## Де лежать runtime-дані

У встановленій/frozen Windows-версії дані користувача мають лежати тут:

```text
%LOCALAPPDATA%\SchoolManager
```

Там можуть бути:

- `school_manager.db`
- Telegram session
- `launcher.log`
- `error_backend.log`
- кеші шаблонів/автоповідомлень/стікерів

Це нормально для користувача, але ці файли не можна класти в реліз.

## Часті проблеми

### Немає `frontend/dist`

Запусти:

```powershell
cd frontend
npm run build
cd ..
```

### PyInstaller не бачить залежність

Перевірити `backend/requirements.txt` і hidden imports у `SchoolManager.spec`.

### Installer зібрався, але містить старі файли

Видалити `dist\SchoolManager` і зібрати заново:

```powershell
Remove-Item dist\SchoolManager -Recurse -Force
pyinstaller SchoolManager.spec --noconfirm --clean
```

Використовуй це тільки для build-output, не для runtime-папок користувача.
