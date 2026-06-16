# macOS Build

Повноцінно macOS-збірку краще робити через GitHub Actions на macOS runner. З Windows напряму `.app/.dmg` надійно не зібрати.

## GitHub Actions

У репозиторії вже є workflow:

```text
.github/workflows/build.yml
```

Він збирає:

- Windows portable.
- Windows installer.
- macOS app/dmg.

macOS job uses `macos-15` and produces one Apple Silicon build artifact.

Запуск вручну:

1. GitHub -> `Actions`.
2. `Build School Manager`.
3. `Run workflow`.
4. Дочекатися `Success`.
5. Завантажити artifacts.

Для release через tag:

```powershell
git tag V2.3
git push origin V2.3
```

Workflow створить GitHub Release тільки для tag-запуску.

## Локальна macOS-збірка

Якщо є Mac:

```bash
cd /path/to/school-manager

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r backend/requirements.txt
pip install pyinstaller

cd frontend
npm ci
npm run build
cd ..

python -m compileall backend desktop_app.py pyinstaller_runtime_hook.py scripts
pyinstaller SchoolManager.macos.spec --noconfirm --clean
python scripts/check_release_clean.py dist/SchoolManager.app
```

Створити unsigned dmg:

```bash
xattr -cr dist/SchoolManager.app || true
codesign --force --deep --sign - dist/SchoolManager.app

mkdir -p dist/dmg
cp -R dist/SchoolManager.app dist/dmg/
hdiutil create -volname "School Manager" -srcfolder dist/dmg -ov -format UDZO dist/SchoolManager-macOS-unsigned.dmg
```

ZIP `.app`:

```bash
ditto -c -k --sequesterRsrc --keepParent dist/SchoolManager.app dist/SchoolManager-macOS-app-unsigned.zip
```

## Runtime-дані на macOS

У frozen macOS-версії дані користувача мають лежати тут:

```text
~/Library/Application Support/SchoolManager
```

У реліз не мають потрапляти:

- `school_manager.db`
- Telegram session
- logs
- caches
- файли шаблонів
- файли автоповідомлень

Перед upload:

```bash
python scripts/check_release_clean.py dist/SchoolManager.app
python scripts/check_release_clean.py dist/SchoolManager-macOS-unsigned.dmg
```

## Перший запуск unsigned app

Поки app не підписаний Apple Developer ID, macOS може показувати попередження.

Варіанти запуску:

1. Right click -> `Open`.
2. Або в Terminal:

```bash
xattr -dr com.apple.quarantine /Applications/SchoolManager.app
open /Applications/SchoolManager.app
```

## Що треба перевірити на Mac

1. Запуск `.app`.
2. Створення runtime-папки в `~/Library/Application Support/SchoolManager`.
3. Telegram login.
4. Синхронізація груп.
5. Відправка повідомлень.
6. Відкриття файлів стандартними програмами.
7. Системні сповіщення.
8. Автозапуск через LaunchAgent.
9. Закриття програми і зупинка backend.

## Важливо

Windows і macOS використовують одну кодну базу. Відмінності мають залишатися в платформних helper-модулях:

- `backend/app_paths.py`
- `backend/platform_autostart.py`
- `backend/system_notifications.py`
- `desktop_app.py`

Якщо треба додати поведінку, залежну від ОС, краще додавати її там, а не розкидати `sys.platform` по UI.
