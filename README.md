# Менеджер Телеграм Груп

Веб-додаток для керування навчальним процесом в батьківських групах Telegram.

## Запуск локально

### Бекенд (Python 3.12)

```bash
cd backend

# Створіть віртуальне середовище
python -m venv venv

# Активуйте (Windows)
venv\Scripts\activate

# Встановіть залежності
pip install -r requirements.txt

# Запустіть сервер
uvicorn main:app --reload --port 8000
```

### Фронтенд (Node.js)

```bash
cd frontend

# Встановіть залежності
npm install

# Запустіть dev сервер
npm run dev
```

## Доступ

- **Фронтенд:** http://localhost:3000
- **Бекенд API:** http://localhost:8000
- **API Документація:** http://localhost:8000/docs

## Структура проекту

```
school_manager/
├── backend/
│   ├── main.py           # FastAPI додаток
│   ├── database.py       # SQLite підключення
│   ├── models.py         # Моделі БД
│   ├── schemas.py        # Pydantic схеми
│   └── routers/          # API ендпоінти
│       ├── groups.py
│       ├── settings.py
│       ├── messages.py
│       └── auto_messages.py
└── frontend/
    ├── src/
    │   ├── App.jsx       # Головний компонент
    │   ├── index.css     # Стилі
    │   └── pages/        # Сторінки
    │       ├── SendMessage.jsx
    │       ├── AutoMessages.jsx
    │       └── Settings.jsx
    └── package.json
```
