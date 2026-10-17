"""Self-contained OAuth result page using the desktop application's palette."""
from html import escape


def oauth_result_page(state):
    # SVG paths from the project's @tabler/icons-react package (MIT).
    title, message, color, icon = {
        'connected': ('Вхід завершено', 'Можете закрити цю вкладку та повернутися до School Manager.', '#22c55e',
                      '<path d="M5 12l5 5l10 -10"/>'),
        'cancelled': ('Вхід не завершено', 'Можете закрити цю вкладку та повторити вхід у School Manager.', '#f59e0b',
                      '<path d="M12 19v.01M12 15v-10"/>'),
        'error': ('Не вдалося завершити вхід', 'Поверніться до School Manager, щоб переглянути повідомлення та повторити вхід.', '#ef4444',
                  '<path d="M18 6l-12 12M6 6l12 12"/>'),
        'pending': ('Завершуємо підключення', 'Поверніться до School Manager, щоб перевірити стан входу. Цю вкладку можна закрити.', '#818cf8',
                    '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0M12 7v5l3 3"/>'),
    }.get(state, ('Некоректний запит', 'Поверніться до School Manager та розпочніть вхід знову.', '#f59e0b',
                  '<path d="M12 19v.01M12 15v-10"/>'))
    return f'''<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="dark">
<title>{escape(title)} · School Manager</title>
<style>
:root {{ color-scheme: dark; font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #f8fafc; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; min-height: 100svh; padding: 24px; display: grid; place-items: center; }}
main {{ width: min(100%, 500px); padding: 28px; background: #1e293b; border: 1px solid #475569; border-radius: 16px; box-shadow: 0 16px 48px #02061766; position: relative; overflow: hidden; }}
main::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(135deg, #6366f1, #8b5cf6); }}
header {{ display: flex; align-items: center; gap: 10px; padding-bottom: 20px; margin-bottom: 24px; border-bottom: 1px solid #334155; }}
.brand-icon {{ width: 34px; height: 34px; padding: 7px; background: #6366f122; border: 1px solid #818cf84d; border-radius: 8px; color: #a5b4fc; flex-shrink: 0; }}
.brand {{ font-size: 15px; font-weight: 650; }}
.service {{ margin-left: auto; color: #aebcd0; font-size: 12px; }}
.status-icon {{ width: 56px; height: 56px; padding: 13px; color: {color}; background: {color}18; border: 1px solid {color}40; border-radius: 16px; margin: 0 auto 18px; }}
svg {{ display: block; width: 100%; height: 100%; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }}
h1 {{ margin: 0 0 10px; font-size: 26px; line-height: 1.25; letter-spacing: -.5px; font-weight: 700; text-align: center; }}
p {{ margin: 0 auto; max-width: 36ch; font-size: 16px; line-height: 1.65; color: #cbd5e1; text-align: center; }}
footer {{ margin-top: 24px; padding-top: 16px; border-top: 1px solid #334155; color: #aebcd0; font-size: 12px; line-height: 1.5; }}
@media (max-width: 480px) {{ body {{ padding: 16px; }} main {{ padding: 22px; }} h1 {{ font-size: 24px; }} header {{ gap: 8px; }} .service {{ font-size: 11px; }} }}
</style>
</head>
<body>
<main aria-labelledby="result-title">
<header><span class="brand-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M22 9l-10 -4l-10 4l10 4l10 -4v6M6 10.6v5.4a6 3 0 0 0 12 0v-5.4"/></svg></span><span class="brand">School Manager</span><span class="service">Google Календар</span></header>
<div class="status-icon" aria-hidden="true"><svg viewBox="0 0 24 24">{icon}</svg></div>
<h1 id="result-title">{escape(title)}</h1>
<p>{escape(message)}</p>
<footer>School Manager · Задачник і календар</footer>
</main>
</body>
</html>'''.encode('utf-8')
