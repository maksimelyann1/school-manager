# Build And Release Quick Commands

Коротка шпаргалка. Детальніше дивись:

- `docs/release.md`
- `docs/build-windows.md`
- `docs/build-macos.md`
- `docs/support.md`

## Windows local

```powershell
cd "D:\Logika\school_manager codex"

cd frontend
npm ci
npm run build
cd ..

python -m compileall backend desktop_app.py pyinstaller_runtime_hook.py scripts
pyinstaller SchoolManager.spec --noconfirm --clean
python scripts\check_release_clean.py dist\SchoolManager

& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
python scripts\check_release_clean.py dist\SchoolManager_Setup.exe
```

## GitHub Actions

```powershell
git push origin main
```

Then GitHub -> `Actions` -> `Build School Manager` -> `Run workflow`.

## Tag release

```powershell
git tag V2.3
git push origin V2.3
```

## Clean artifact check only

```powershell
.\check_release_clean.bat dist\SchoolManager
python scripts\check_release_clean.py dist\SchoolManager_Setup.exe
```
