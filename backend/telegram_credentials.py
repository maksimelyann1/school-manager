from dataclasses import dataclass


_DEFAULT_API_ID_PARTS = ("397", "196", "77")
_HASH_KEY = (19, 71, 103, 41, 5, 83, 31)
_HASH_MASKED = (
    113, 112, 1, 75, 52, 54, 40, 118,
    114, 82, 74, 49, 106, 125, 32, 118,
    82, 77, 102, 103, 42, 43, 38, 5,
    28, 61, 97, 40, 114, 33, 1, 74,
)


@dataclass(frozen=True)
class TelegramCredentials:
    api_id: int
    api_hash: str
    source: str


def _decode_default_hash() -> str:
    chars = [
        chr(value ^ _HASH_KEY[index % len(_HASH_KEY)])
        for index, value in enumerate(_HASH_MASKED)
    ]
    return "".join(chars)


def get_default_credentials() -> TelegramCredentials:
    return TelegramCredentials(
        api_id=int("".join(_DEFAULT_API_ID_PARTS)),
        api_hash=_decode_default_hash(),
        source="built_in",
    )


def has_default_credentials() -> bool:
    credentials = get_default_credentials()
    return bool(credentials.api_id and credentials.api_hash)


def stored_credentials_match_default(settings=None) -> bool:
    if not settings:
        return False
    custom_api_id = str(getattr(settings, "api_id", "") or "").strip()
    custom_api_hash = str(getattr(settings, "api_hash", "") or "").strip()
    default_credentials = get_default_credentials()
    return (
        custom_api_id == str(default_credentials.api_id)
        and custom_api_hash == default_credentials.api_hash
    )


def get_effective_credentials(settings=None) -> TelegramCredentials:
    custom_api_id = str(getattr(settings, "api_id", "") or "").strip()
    custom_api_hash = str(getattr(settings, "api_hash", "") or "").strip()

    if custom_api_id and custom_api_hash:
        return TelegramCredentials(
            api_id=int(custom_api_id),
            api_hash=custom_api_hash,
            source="custom",
        )

    return get_default_credentials()
