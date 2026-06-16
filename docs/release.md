# Release Checklist

Цей файл - короткий порядок дій перед кожною публічною версією School Manager.

## 1. Перед релізом

1. Перевірити, що програма стабільно запускається локально через `ЗАПУСК.bat`.
2. Перевірити основні сценарії:
   - Telegram-авторизація і синхронізація груп.
   - Відправка повідомлення у тестову групу.
   - Шаблони з файлами.
   - Автоповідомлення.
   - `Звіт батькам`.
   - Збереження diagnostic log.
3. Переконатися, що в робочу директорію не потрапили файли користувача:
   - `school_manager.db`
   - `*.session`
   - `*.log`
   - `template_files/`
   - `auto_message_files/`
   - `import_cache/`
   - `sticker_cache/`
   - `.env`
   - `tokens.json`

Ці файли мають бути локальними runtime-даними і не повинні йти в GitHub або реліз.

## 2. Оновити версію

Перед публічним релізом змінити версію в таких місцях:

- `backend/version_config.py` -> `APP_VERSION`
- `frontend/package.json` -> `version`
- `installer.iss` -> `AppVersion`
- `SchoolManager.macos.spec` -> `CFBundleShortVersionString` і `CFBundleVersion`
- `update-info-vX.Y.json` або актуальний JSON у gist/release-сховищі

Формат update JSON:

```json
{
  "latest_version": "2.3",
  "changelog": "Короткий опис змін",
  "downloads": {
    "windows": {
      "url": "https://example.com/SchoolManager_Setup.exe"
    },
    "macos": {
      "url": "https://example.com/SchoolManager-macOS-unsigned.dmg"
    }
  }
}
```

Постійне посилання для перевірки оновлень зараз задане в `backend/version_config.py`.

## 3. Локальні перевірки

```powershell
cd "D:\Logika\school_manager codex"

cd frontend
npm run build
cd ..

python -m compileall backend desktop_app.py pyinstaller_runtime_hook.py scripts
python -m py_compile scripts\check_release_clean.py
```

Якщо вже є локальна збірка:

```powershell
python scripts\check_release_clean.py dist\SchoolManager
python scripts\check_release_clean.py dist\SchoolManager_Setup.exe
```

Або через bat-файл:

```powershell
.\check_release_clean.bat dist\SchoolManager
```

## 4. Перевірка чистоти релізу

Перед завантаженням релізу обов’язково запускати:

```powershell
python scripts\check_release_clean.py dist\SchoolManager
python scripts\check_release_clean.py dist\SchoolManager_Setup.exe
```

Скрипт має знайти проблему, якщо в artifact випадково потрапили:

- база `.db`;
- Telegram session;
- log-файли;
- `.env`;
- `tokens.json`;
- кеші/папки файлів користувача;
- Google AI API key або інші схожі секрети.

Вбудоване readonly-посилання на базу звітів лишається частиною програми і не є runtime-даними користувача.

## 5. GitHub Actions build

У GitHub:

1. Відкрити репозиторій.
2. Перейти в `Actions`.
3. Обрати `Build School Manager`.
4. Натиснути `Run workflow`.
5. Дочекатися статусу `Success`.
6. Завантажити artifacts:
   - Windows portable.
   - Windows installer.
   - macOS app/dmg.

Workflow також запускається автоматично для тегів:

```powershell
git tag V2.3
git push origin V2.3
```

Для тегів workflow створює GitHub Release.

## 6. Після релізу

1. Завантажити installer/dmg у потрібне місце публікації.
2. Оновити JSON оновлень.
3. Перевірити, що посилання з JSON відкриваються у браузері.
4. Запустити стару версію програми і перевірити, що вона бачить нову версію.
5. Встановити нову версію поверх старої і перевірити, що дані користувача залишилися.
