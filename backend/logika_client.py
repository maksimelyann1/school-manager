import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

logger = logging.getLogger("logika_client")

LOGIKA_BACKOFFICE_URL = "https://backoffice.logikaschool.com.ua/"
LOGIKA_API_URL = "https://api.logikaschool.com.ua"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Origin": "https://backoffice.logikaschool.com.ua",
    "Referer": "https://backoffice.logikaschool.com.ua/",
    "Accept": "application/json, text/plain, */*",
}


class LogikaAuthError(Exception):
    """Помилка авторизації Logika."""
    pass


class LogikaClient:
    def __init__(
        self,
        login: Optional[str] = None,
        password: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        xsrf_token: Optional[str] = None,
    ):
        self.login_user = login
        self.password = password
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.xsrf_token = xsrf_token

    def authenticate(self) -> Dict[str, Any]:
        """Виконує вхід через фоновий браузер для безпечного проходження шифрування та отримання токенів."""
        if not self.login_user or not self.password:
            raise LogikaAuthError("Логін або пароль не вказані")

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument(f"--user-agent={DEFAULT_HEADERS['User-Agent']}")

        driver = None
        try:
            driver = webdriver.Chrome(options=opts)
            driver.get(LOGIKA_BACKOFFICE_URL)
            time.sleep(2.5)

            login_input = driver.find_element(By.ID, "login")
            pass_input = driver.find_element(By.ID, "password")
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")

            login_input.clear()
            login_input.send_keys(self.login_user)
            pass_input.clear()
            pass_input.send_keys(self.password)
            submit_btn.click()

            time.sleep(3.5)

            # Перевіряємо помилки на сторінці
            cur_url = driver.current_url
            if "/login" in cur_url:
                # Можливо неправильний логін чи пароль
                body_text = driver.find_element(By.TAG_NAME, "body").text
                if "Bad credentials" in body_text or "Невірний" in body_text or "error" in body_text.lower():
                    raise LogikaAuthError("Невірний логін або пароль")
                # Дамо ще секунду
                time.sleep(2)
                if "/login" in driver.current_url:
                    raise LogikaAuthError("Не вдалося авторизуватися в Logika")

            token = driver.execute_script("return localStorage.getItem('LOGIKA_ACCESS_TOKEN');")
            refresh_tok = driver.execute_script("return localStorage.getItem('LOGIKA_REFRESH_TOKEN');")
            xsrf = driver.execute_script("return localStorage.getItem('LOGIKA_X-XSRF-TOKEN');")
            exp_date = driver.execute_script("return localStorage.getItem('LOGIKA_ACCESS_TOKEN_EXPIRATION_DATE');")

            if not token:
                raise LogikaAuthError("Токен авторизації не знайдено після входу")

            self.access_token = token
            self.refresh_token = refresh_tok
            self.xsrf_token = xsrf

            return {
                "access_token": token,
                "refresh_token": refresh_tok,
                "xsrf_token": xsrf,
                "token_expires_at": exp_date,
            }
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def _get_http_client(self) -> httpx.Client:
        headers = dict(DEFAULT_HEADERS)
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.xsrf_token:
            headers["X-XSRF-TOKEN"] = self.xsrf_token
        return httpx.Client(headers=headers, timeout=25.0)

    def refresh_access_token(self) -> Dict[str, Any]:
        """Оновлює токен через refresh_token або повторний вхід."""
        if self.refresh_token:
            try:
                with self._get_http_client() as client:
                    resp = client.post(
                        f"{LOGIKA_API_URL}/auth/refresh_token",
                        json={"refreshToken": self.refresh_token},
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    self.access_token = data.get("accessToken", self.access_token)
                    self.refresh_token = data.get("refreshToken", self.refresh_token)
                    return {
                        "access_token": self.access_token,
                        "refresh_token": self.refresh_token,
                        "xsrf_token": self.xsrf_token,
                    }
            except Exception as e:
                logger.warning(f"Помилка refresh_token: {e}")

        # Якщо refresh не спрацював, робимо повноцінний вхід
        return self.authenticate()

    def _authorized_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Виконує HTTP-запит з автоматичним оновленням токену при 401."""
        if not self.access_token:
            self.authenticate()

        with self._get_http_client() as client:
            resp = client.request(method, url, **kwargs)
            if resp.status_code == 401:
                self.refresh_access_token()
                with self._get_http_client() as retry_client:
                    resp = retry_client.request(method, url, **kwargs)
            return resp

    def get_schedule(
        self,
        page: int = 0,
        size: int = 100,
        teacher_id: Optional[int] = None,
        status: str = "ACTIVE",
        active: bool = True,
        is_start_day_now: bool = True,
    ) -> List[Dict[str, Any]]:
        """Отримує список уроків викладача."""
        params = {
            "page": page,
            "size": size,
            "status": status,
            "isStartDayNow": "true" if is_start_day_now else "false",
            "active": "true" if active else "false",
            "deleted": "false",
        }
        if teacher_id:
            params["currentEmployeeId"] = teacher_id
        resp = self._authorized_request("GET", f"{LOGIKA_API_URL}/schedule", params=params)
        if resp.status_code != 200:
            raise Exception(f"Не вдалося отримати розклад: HTTP {resp.status_code} {resp.text[:200]}")
        
        data = resp.json()
        return data.get("content", [])

    def get_group_schedule(self, group_id: int) -> List[Dict[str, Any]]:
        """Отримує повний розклад усіх уроків для конкретної групи."""
        resp = self._authorized_request(
            "GET",
            f"{LOGIKA_API_URL}/schedule",
            params={"groupId": group_id, "size": 100},
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("content", [])

    def get_attendance(self, schedule_id: int) -> List[Dict[str, Any]]:
        """Отримує журнал відвідуваності уроку."""
        resp = self._authorized_request(
            "GET",
            f"{LOGIKA_API_URL}/attendance",
            params={"scheduleId": schedule_id},
        )
        if resp.status_code != 200:
            raise Exception(f"Не вдалося отримати журнал уроку {schedule_id}: HTTP {resp.status_code}")
        return resp.json()

    def get_absent_students(self, schedule_id: int) -> List[str]:
        """Повертає список імен учнів, які були відсутні на уроці."""
        records = self.get_attendance(schedule_id)
        absents = []
        for r in records:
            state = (r.get("state") or "").upper()
            # Учні зі статусом ABSENT
            if state in ("ABSENT", "MISSED"):
                student_info = r.get("studentId") or {}
                name = student_info.get("value") or ""
                if name.strip():
                    absents.append(name.strip())
        return absents
