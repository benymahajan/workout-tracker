"""Checks that common ways of pasting a service-account private key into secrets still load."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from google.oauth2.service_account import Credentials  # noqa: E402

from store import normalize_service_account  # noqa: E402

PEM = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()

BASE = {
    "type": "service_account",
    "project_id": "test-project",
    "private_key_id": "abc123",
    "private_key": PEM,
    "client_email": "gym@test-project.iam.gserviceaccount.com",
    "client_id": "1234",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def loads(key):
    info = normalize_service_account({**BASE, "private_key": key})
    return Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])


class PrivateKeyPastes(unittest.TestCase):
    def test_real_newlines(self):
        self.assertEqual(loads(PEM).service_account_email, BASE["client_email"])

    def test_literal_backslash_n(self):
        self.assertEqual(loads(PEM.replace("\n", "\\n")).service_account_email, BASE["client_email"])

    def test_stray_quotes_and_crlf(self):
        self.assertEqual(loads('"' + PEM.replace("\n", "\r\n") + '"').service_account_email, BASE["client_email"])

    def test_normalize_is_idempotent(self):
        once = normalize_service_account(BASE)
        twice = normalize_service_account(once)
        self.assertEqual(once["private_key"], twice["private_key"])


if __name__ == "__main__":
    unittest.main()
