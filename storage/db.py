import json
from pathlib import Path
from typing import Optional

import aiosqlite

from storage.crypto import TokenCipher
from storage.models import DEFAULT_SETTINGS, User


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    vk_token_encrypted TEXT NOT NULL,
    vk_user_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    settings TEXT NOT NULL,
    last_notification_ts INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS message_map (
    tg_chat_id INTEGER NOT NULL,
    tg_message_id INTEGER NOT NULL,
    vk_peer_id INTEGER NOT NULL,
    vk_message_id INTEGER,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (tg_chat_id, tg_message_id)
);

CREATE INDEX IF NOT EXISTS idx_message_map_created ON message_map(created_at);

CREATE TABLE IF NOT EXISTS vkid_session (
    tg_id INTEGER PRIMARY KEY,
    access_token_encrypted TEXT NOT NULL,
    cookies_encrypted TEXT NOT NULL,
    expires_at INTEGER NOT NULL DEFAULT 0,
    logout_hash TEXT,
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    last_success_at INTEGER DEFAULT 0,
    stall_alert_sent_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vkid_devices (
    tg_id INTEGER NOT NULL,
    device_id TEXT NOT NULL,
    trust TEXT NOT NULL DEFAULT 'unknown',
    last_seen_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    device_name TEXT,
    device_os TEXT,
    last_city TEXT,
    last_ip TEXT,
    PRIMARY KEY (tg_id, device_id)
);

CREATE TABLE IF NOT EXISTS vkid_trust (
    tg_id INTEGER NOT NULL,
    trust_key TEXT NOT NULL,
    trust TEXT NOT NULL DEFAULT 'unknown',
    device_name TEXT,
    device_os TEXT,
    app_name TEXT,
    last_city TEXT,
    last_ip TEXT,
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (tg_id, trust_key)
);

CREATE TABLE IF NOT EXISTS vkid_seen_sessions (
    tg_id INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    first_seen_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (tg_id, fingerprint)
);
"""


class Database:
    def __init__(self, path: Path, cipher: TokenCipher) -> None:
        self._path = path
        self._cipher = cipher

    async def init(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(SCHEMA)
            db.row_factory = aiosqlite.Row

            # миграция: добавить vk_message_id если колонки нет
            cursor = await db.execute("PRAGMA table_info(message_map)")
            cols = {row["name"] for row in await cursor.fetchall()}
            if "vk_message_id" not in cols:
                await db.execute("ALTER TABLE message_map ADD COLUMN vk_message_id INTEGER")

            # миграция: last_success_at / stall_alert_sent_at в vkid_session
            cursor = await db.execute("PRAGMA table_info(vkid_session)")
            vs_cols = {row["name"] for row in await cursor.fetchall()}
            if "last_success_at" not in vs_cols:
                await db.execute("ALTER TABLE vkid_session ADD COLUMN last_success_at INTEGER DEFAULT 0")
            if "stall_alert_sent_at" not in vs_cols:
                await db.execute("ALTER TABLE vkid_session ADD COLUMN stall_alert_sent_at INTEGER DEFAULT 0")

            # миграция: web-сессия vk.com (cookies + срок токена)
            cursor = await db.execute("PRAGMA table_info(users)")
            user_cols = {row["name"] for row in await cursor.fetchall()}
            if "vk_cookies_encrypted" not in user_cols:
                await db.execute("ALTER TABLE users ADD COLUMN vk_cookies_encrypted TEXT")
            if "vk_token_expires_at" not in user_cols:
                await db.execute(
                    "ALTER TABLE users ADD COLUMN vk_token_expires_at INTEGER NOT NULL DEFAULT 0"
                )
            if "vk_app_id" not in user_cols:
                await db.execute("ALTER TABLE users ADD COLUMN vk_app_id INTEGER NOT NULL DEFAULT 0")

            await db.commit()

    def _row_to_user(self, row: aiosqlite.Row) -> User:
        keys = set(row.keys())
        cookies_enc = row["vk_cookies_encrypted"] if "vk_cookies_encrypted" in keys else None
        cookies = ""
        if cookies_enc:
            try:
                cookies = self._cipher.decrypt(cookies_enc)
            except Exception:
                cookies = ""
        expires_at = 0
        if "vk_token_expires_at" in keys and row["vk_token_expires_at"] is not None:
            expires_at = int(row["vk_token_expires_at"])
        app_id = 0
        if "vk_app_id" in keys and row["vk_app_id"] is not None:
            app_id = int(row["vk_app_id"])
        return User(
            tg_id=row["tg_id"],
            vk_token=self._cipher.decrypt(row["vk_token_encrypted"]),
            vk_user_id=row["vk_user_id"],
            enabled=bool(row["enabled"]),
            settings={**DEFAULT_SETTINGS, **json.loads(row["settings"])},
            last_notification_ts=row["last_notification_ts"],
            vk_cookies=cookies,
            vk_token_expires_at=expires_at,
            vk_app_id=app_id,
        )

    async def upsert_user(
        self,
        tg_id: int,
        vk_token: str,
        vk_user_id: int,
        vk_cookies: str = "",
        vk_token_expires_at: int = 0,
        vk_app_id: int = 0,
    ) -> User:
        encrypted = self._cipher.encrypt(vk_token)
        cookies_enc = self._cipher.encrypt(vk_cookies) if vk_cookies else ""
        settings_json = json.dumps(DEFAULT_SETTINGS)
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                INSERT INTO users (
                    tg_id, vk_token_encrypted, vk_user_id, enabled, settings,
                    vk_cookies_encrypted, vk_token_expires_at, vk_app_id
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET
                    vk_token_encrypted=excluded.vk_token_encrypted,
                    vk_user_id=excluded.vk_user_id,
                    enabled=1,
                    vk_cookies_encrypted=excluded.vk_cookies_encrypted,
                    vk_token_expires_at=excluded.vk_token_expires_at,
                    vk_app_id=excluded.vk_app_id
                """,
                (
                    tg_id,
                    encrypted,
                    vk_user_id,
                    settings_json,
                    cookies_enc,
                    vk_token_expires_at,
                    vk_app_id,
                ),
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
            row = await cursor.fetchone()
        return self._row_to_user(row)

    async def update_vk_session(
        self,
        tg_id: int,
        vk_token: str,
        vk_cookies: str,
        vk_token_expires_at: int,
        vk_app_id: int,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                UPDATE users
                SET vk_token_encrypted = ?,
                    vk_cookies_encrypted = ?,
                    vk_token_expires_at = ?,
                    vk_app_id = ?
                WHERE tg_id = ?
                """,
                (
                    self._cipher.encrypt(vk_token),
                    self._cipher.encrypt(vk_cookies) if vk_cookies else "",
                    vk_token_expires_at,
                    vk_app_id,
                    tg_id,
                ),
            )
            await db.commit()

    async def get_user(self, tg_id: int) -> Optional[User]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
            row = await cursor.fetchone()
        return self._row_to_user(row) if row else None

    async def list_active_users(self) -> list[User]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM users WHERE enabled = 1")
            rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def set_enabled(self, tg_id: int, enabled: bool) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE users SET enabled = ? WHERE tg_id = ?",
                (1 if enabled else 0, tg_id),
            )
            await db.commit()

    async def delete_user(self, tg_id: int) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("DELETE FROM users WHERE tg_id = ?", (tg_id,))
            await db.commit()

    async def update_settings(self, tg_id: int, settings: dict[str, bool]) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE users SET settings = ? WHERE tg_id = ?",
                (json.dumps(settings), tg_id),
            )
            await db.commit()

    async def update_last_notification_ts(self, tg_id: int, ts: int) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE users SET last_notification_ts = ? WHERE tg_id = ?",
                (ts, tg_id),
            )
            await db.commit()

    async def save_message_map(
        self,
        tg_chat_id: int,
        tg_message_id: int,
        vk_peer_id: int,
        vk_message_id: Optional[int] = None,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO message_map (tg_chat_id, tg_message_id, vk_peer_id, vk_message_id)
                VALUES (?, ?, ?, ?)
                """,
                (tg_chat_id, tg_message_id, vk_peer_id, vk_message_id),
            )
            await db.commit()

    # --- VK ID ---

    async def upsert_vkid_session(
        self,
        tg_id: int,
        access_token: str,
        cookies: str,
        expires_at: int,
        logout_hash: Optional[str],
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO vkid_session (tg_id, access_token_encrypted, cookies_encrypted, expires_at, logout_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, strftime('%s','now'))
                ON CONFLICT(tg_id) DO UPDATE SET
                    access_token_encrypted=excluded.access_token_encrypted,
                    cookies_encrypted=excluded.cookies_encrypted,
                    expires_at=excluded.expires_at,
                    logout_hash=excluded.logout_hash,
                    updated_at=excluded.updated_at
                """,
                (
                    tg_id,
                    self._cipher.encrypt(access_token),
                    self._cipher.encrypt(cookies),
                    expires_at,
                    logout_hash,
                ),
            )
            await db.commit()

    async def update_vkid_token(
        self,
        tg_id: int,
        access_token: str,
        expires_at: int,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                UPDATE vkid_session
                SET access_token_encrypted = ?, expires_at = ?, updated_at = strftime('%s','now')
                WHERE tg_id = ?
                """,
                (self._cipher.encrypt(access_token), expires_at, tg_id),
            )
            await db.commit()

    async def get_vkid_session(self, tg_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM vkid_session WHERE tg_id = ?", (tg_id,))
            row = await cursor.fetchone()
        if not row:
            return None
        return {
            "tg_id": row["tg_id"],
            "access_token": self._cipher.decrypt(row["access_token_encrypted"]),
            "cookies": self._cipher.decrypt(row["cookies_encrypted"]),
            "expires_at": row["expires_at"],
            "logout_hash": row["logout_hash"],
            "last_success_at": row["last_success_at"] or 0,
            "stall_alert_sent_at": row["stall_alert_sent_at"] or 0,
        }

    async def mark_vkid_tick_success(self, tg_id: int) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                UPDATE vkid_session
                SET last_success_at = strftime('%s','now'), stall_alert_sent_at = 0
                WHERE tg_id = ?
                """,
                (tg_id,),
            )
            await db.commit()

    async def mark_vkid_stall_alert_sent(self, tg_id: int) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE vkid_session SET stall_alert_sent_at = strftime('%s','now') WHERE tg_id = ?",
                (tg_id,),
            )
            await db.commit()

    async def delete_vkid_session(self, tg_id: int) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("DELETE FROM vkid_session WHERE tg_id = ?", (tg_id,))
            await db.execute("DELETE FROM vkid_devices WHERE tg_id = ?", (tg_id,))
            await db.execute("DELETE FROM vkid_trust WHERE tg_id = ?", (tg_id,))
            await db.execute("DELETE FROM vkid_seen_sessions WHERE tg_id = ?", (tg_id,))
            await db.commit()

    async def upsert_vkid_device(
        self,
        tg_id: int,
        device_id: str,
        device_name: Optional[str],
        device_os: Optional[str],
        city: Optional[str],
        ip: Optional[str],
        trust: Optional[str] = None,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            if trust is None:
                # обновляем только «последние виденные» данные, trust не трогаем
                await db.execute(
                    """
                    INSERT INTO vkid_devices (tg_id, device_id, device_name, device_os, last_city, last_ip, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'))
                    ON CONFLICT(tg_id, device_id) DO UPDATE SET
                        device_name = COALESCE(excluded.device_name, vkid_devices.device_name),
                        device_os = COALESCE(excluded.device_os, vkid_devices.device_os),
                        last_city = excluded.last_city,
                        last_ip = excluded.last_ip,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (tg_id, device_id, device_name, device_os, city, ip),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO vkid_devices (tg_id, device_id, device_name, device_os, last_city, last_ip, last_seen_at, trust)
                    VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'), ?)
                    ON CONFLICT(tg_id, device_id) DO UPDATE SET
                        device_name = COALESCE(excluded.device_name, vkid_devices.device_name),
                        device_os = COALESCE(excluded.device_os, vkid_devices.device_os),
                        last_city = excluded.last_city,
                        last_ip = excluded.last_ip,
                        last_seen_at = excluded.last_seen_at,
                        trust = excluded.trust
                    """,
                    (tg_id, device_id, device_name, device_os, city, ip, trust),
                )
            await db.commit()

    async def get_vkid_device_trust(self, tg_id: int, device_id: str) -> Optional[str]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT trust FROM vkid_devices WHERE tg_id = ? AND device_id = ?",
                (tg_id, device_id),
            )
            row = await cursor.fetchone()
        return row["trust"] if row else None

    async def set_vkid_device_trust(self, tg_id: int, device_id: str, trust: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE vkid_devices SET trust = ? WHERE tg_id = ? AND device_id = ?",
                (trust, tg_id, device_id),
            )
            await db.commit()

    async def upsert_vkid_trust(
        self,
        tg_id: int,
        trust_key: str,
        device_name: Optional[str],
        device_os: Optional[str],
        app_name: Optional[str],
        city: Optional[str],
        ip: Optional[str],
        trust: Optional[str] = None,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            if trust is None:
                await db.execute(
                    """
                    INSERT INTO vkid_trust (tg_id, trust_key, device_name, device_os, app_name, last_city, last_ip, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
                    ON CONFLICT(tg_id, trust_key) DO UPDATE SET
                        device_name = COALESCE(excluded.device_name, vkid_trust.device_name),
                        device_os = COALESCE(excluded.device_os, vkid_trust.device_os),
                        app_name = COALESCE(excluded.app_name, vkid_trust.app_name),
                        last_city = excluded.last_city,
                        last_ip = excluded.last_ip,
                        updated_at = excluded.updated_at
                    """,
                    (tg_id, trust_key, device_name, device_os, app_name, city, ip),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO vkid_trust (tg_id, trust_key, device_name, device_os, app_name, last_city, last_ip, trust, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
                    ON CONFLICT(tg_id, trust_key) DO UPDATE SET
                        device_name = COALESCE(excluded.device_name, vkid_trust.device_name),
                        device_os = COALESCE(excluded.device_os, vkid_trust.device_os),
                        app_name = COALESCE(excluded.app_name, vkid_trust.app_name),
                        last_city = excluded.last_city,
                        last_ip = excluded.last_ip,
                        trust = excluded.trust,
                        updated_at = excluded.updated_at
                    """,
                    (tg_id, trust_key, device_name, device_os, app_name, city, ip, trust),
                )
            await db.commit()

    async def get_vkid_trust(self, tg_id: int, trust_key: str) -> Optional[str]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT trust FROM vkid_trust WHERE tg_id = ? AND trust_key = ?",
                (tg_id, trust_key),
            )
            row = await cursor.fetchone()
        return row["trust"] if row else None

    async def set_vkid_trust(self, tg_id: int, trust_key: str, trust: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO vkid_trust (tg_id, trust_key, trust)
                VALUES (?, ?, ?)
                ON CONFLICT(tg_id, trust_key) DO UPDATE SET
                    trust = excluded.trust,
                    updated_at = strftime('%s','now')
                """,
                (tg_id, trust_key, trust),
            )
            await db.commit()

    async def has_seen_vkid_session(self, tg_id: int, fingerprint: str) -> bool:
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM vkid_seen_sessions WHERE tg_id = ? AND fingerprint = ?",
                (tg_id, fingerprint),
            )
            return await cursor.fetchone() is not None

    async def mark_seen_vkid_session(self, tg_id: int, fingerprint: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO vkid_seen_sessions (tg_id, fingerprint) VALUES (?, ?)",
                (tg_id, fingerprint),
            )
            await db.commit()

    async def get_vk_target_for_message(
        self,
        tg_chat_id: int,
        tg_message_id: int,
    ) -> Optional[tuple[int, Optional[int]]]:
        """Возвращает (vk_peer_id, vk_message_id) или None."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT vk_peer_id, vk_message_id FROM message_map WHERE tg_chat_id = ? AND tg_message_id = ?",
                (tg_chat_id, tg_message_id),
            )
            row = await cursor.fetchone()
        if not row:
            return None
        return row["vk_peer_id"], row["vk_message_id"]
