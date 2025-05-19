import sqlite3
import os
import hashlib
import binascii
import hmac
from typing import Optional, Tuple

class DatabaseManager:
    """
    Handles user storage with SQLite, password hashing, and verification.
    """
    def __init__(self, db_path: str = "assets/chat.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_users_table()

    def _create_users_table(self):
        """Create users table if it doesn’t exist."""
        sql = '''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL
        )
        '''
        self.conn.execute(sql)
        self.conn.commit()

    def _hash_password(self, password: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
        """
        Hash a password with salt using PBKDF2 HMAC SHA256.
        Returns (salt_hex, hash_hex).
        """
        if salt is None:
            salt = os.urandom(16)
        pwd_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100_000
        )
        salt_hex = binascii.hexlify(salt).decode('ascii')
        hash_hex = binascii.hexlify(pwd_hash).decode('ascii')
        return salt_hex, hash_hex

    def user_exists(self, username: str) -> bool:
        """Check if a username already exists."""
        cursor = self.conn.execute(
            "SELECT 1 FROM users WHERE username = ? LIMIT 1", (username,)
        )
        return cursor.fetchone() is not None

    def create_user(self, username: str, password: str) -> bool:
        """Create a new user with hashed password. Returns True on success."""
        if self.user_exists(username):
            return False
        salt, pwd_hash = self._hash_password(password)
        try:
            self.conn.execute(
                "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                (username, pwd_hash, salt)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def verify_password(self, username: str, password: str) -> bool:
        """Verify a user’s password. Returns True if match."""
        cursor = self.conn.execute(
            "SELECT password_hash, salt FROM users WHERE username = ?", (username,)
        )
        row = cursor.fetchone()
        if not row:
            return False
        stored_hash, salt_hex = row
        salt = binascii.unhexlify(salt_hex)
        _, calc_hash = self._hash_password(password, salt)
        # Use hmac.compare_digest for secure comparison
        return hmac.compare_digest(calc_hash, stored_hash)

    def close(self):
        """Close DB connection."""
        self.conn.close()