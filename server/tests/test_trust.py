import hashlib
import ssl
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from verify_trust import check_context


class TrustVerificationTest(unittest.TestCase):
    def test_rejects_actual_emsign_root_in_a_real_ssl_context(self):
        context = ssl.create_default_context()
        root = Path(__file__).parent / "fixtures" / "emsign-ecc-root-g3.pem"
        context.load_verify_locations(cafile=str(root))
        with self.assertRaisesRegex(RuntimeError, "compromised issuer trusted"):
            check_context("contaminated system bundle", context)

    def setUp(self):
        self.context = Mock(verify_mode=ssl.CERT_REQUIRED, check_hostname=True)
        self.context.get_ca_certs.return_value = [b"unaffected root"]

    def test_rejects_a_blocked_issuer_even_in_a_mixed_bundle(self):
        blocked_der = b"blocked root"
        fingerprint = hashlib.sha256(blocked_der).hexdigest()
        self.context.get_ca_certs.return_value.append(blocked_der)
        with patch("verify_trust.BLOCKED_ROOTS", {fingerprint: "blocked issuer"}):
            with self.assertRaisesRegex(RuntimeError, "compromised issuer trusted"):
                check_context("test", self.context)

    def test_rejects_empty_or_disabled_verification(self):
        self.context.get_ca_certs.return_value = []
        with self.assertRaisesRegex(RuntimeError, "empty trust store"):
            check_context("test", self.context)
        self.context.verify_mode = ssl.CERT_NONE
        with self.assertRaisesRegex(RuntimeError, "verification disabled"):
            check_context("test", self.context)
        self.context.verify_mode = ssl.CERT_REQUIRED
        self.context.check_hostname = False
        with self.assertRaisesRegex(RuntimeError, "verification disabled"):
            check_context("test", self.context)

    def test_accepts_unaffected_roots(self):
        self.assertEqual(check_context("test", self.context), {"roots": 1, "blocked_issuers": 0})


if __name__ == "__main__":
    unittest.main()
