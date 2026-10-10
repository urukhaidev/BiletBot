import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def authenticate(init_data, token, now=None):
    if not init_data or len(init_data) > 16384:
        raise ValueError("Откройте приложение из Telegram")
    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)
    if len(pairs) != len(data):
        raise ValueError("Некорректные данные Telegram")
    supplied = data.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ValueError("Не удалось подтвердить сессию Telegram")
    age = (time.time() if now is None else now) - int(data.get("auth_date", "0"))
    if age < -30 or age > 86400:
        raise ValueError("Сессия истекла. Откройте приложение заново")
    user = json.loads(data["user"])
    if not isinstance(user.get("id"), int) or user["id"] <= 0:
        raise ValueError("Некорректный пользователь")
    return user
