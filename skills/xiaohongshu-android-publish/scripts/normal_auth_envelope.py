"""Public, secret-silent RSA-OAEP handoff decoder. No device operations.

Import decrypt_envelope inside the existing bounded normal-auth script.
The return value is sensitive: use only in memory; never print/write it.
CLI supports dummy self-test only. Caller owns finally cleanup of key/cipher.
"""
import hashlib
import json
import re
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class EnvelopeError(ValueError):
    pass


def _check(ok, label):
    if not ok:
        raise EnvelopeError(label)


def _oaep():
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def decrypt_envelope(envelope, private_key_pem, *, expected_key_sha256, expected_nonce, expected_task):
    """Return original human message in memory, or a value-free error."""
    _check(isinstance(envelope, dict), 'outer_object_required')
    _check(set(envelope) == {'ciphertext_hex', 'algorithm', 'mgf1', 'label', 'key_sha256', 'nonce'}, 'outer_fields_mismatch')
    _check(envelope['algorithm'] == 'RSA-OAEP-SHA256', 'algorithm_mismatch')
    _check(envelope['mgf1'] == 'SHA256', 'mgf1_mismatch')
    _check(envelope['label'] is None, 'label_must_be_null')
    _check(envelope['key_sha256'] == expected_key_sha256, 'outer_key_fingerprint_mismatch')
    _check(envelope['nonce'] == expected_nonce, 'outer_nonce_mismatch')
    try:
        key = serialization.load_pem_private_key(private_key_pem, password=None)
        _check(isinstance(key, rsa.RSAPrivateKey) and key.key_size >= 2048, 'rsa_key_invalid')
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        _check(hashlib.sha256(public).hexdigest() == expected_key_sha256, 'private_public_fingerprint_mismatch')
        value = envelope['ciphertext_hex']
        _check(isinstance(value, str) and re.fullmatch(r'[0-9a-f]+', value) is not None, 'ciphertext_hex_invalid')
        _check(len(value) == key.key_size // 4, 'ciphertext_length_mismatch')
        body = json.loads(key.decrypt(bytes.fromhex(value), _oaep()).decode('utf-8'))
    except EnvelopeError:
        raise
    except Exception:
        raise EnvelopeError('decryption_or_payload_encoding_failed') from None
    _check(isinstance(body, dict) and set(body) == {'t', 'n', 's'}, 'inner_fields_mismatch')
    _check(body['t'] == expected_task, 'inner_task_mismatch')
    _check(body['n'] == expected_nonce, 'inner_nonce_mismatch')
    _check(isinstance(body['s'], str) and 0 < len(body['s'].encode('utf-8')) <= 256, 'inner_message_invalid')
    return body['s']


class DummyEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private = cls.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        pub = cls.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.sha = hashlib.sha256(pub).hexdigest()
        cls.nonce = 'dummy-test-only-nonce'
        cls.task = 'dummy-test-only-task'

    def envelope(self, body=None):
        body = body or {'t': self.task, 'n': self.nonce, 's': 'DUMMY-非手机凭据-不执行设备操作'}
        ciphertext = self.key.public_key().encrypt(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), _oaep())
        return {'ciphertext_hex': ciphertext.hex(), 'algorithm': 'RSA-OAEP-SHA256', 'mgf1': 'SHA256', 'label': None, 'key_sha256': self.sha, 'nonce': self.nonce}

    def decode(self, envelope, **overrides):
        kwargs = {'expected_key_sha256': self.sha, 'expected_nonce': self.nonce, 'expected_task': self.task}
        kwargs.update(overrides)
        return decrypt_envelope(envelope, self.private, **kwargs)

    def test_exact_envelope_unicode_roundtrip(self):
        self.assertEqual(self.decode(self.envelope()), 'DUMMY-非手机凭据-不执行设备操作')

    def test_algorithm_mgf_and_label_are_exact(self):
        for key, value in [('algorithm', 'RSA-OAEP-SHA-256'), ('mgf1', 'SHA1'), ('label', '')]:
            e = self.envelope(); e[key] = value
            with self.assertRaises(EnvelopeError): self.decode(e)

    def test_outer_nonce_and_fingerprint_fail_closed(self):
        for key in ['nonce', 'key_sha256']:
            e = self.envelope(); e[key] = 'different'
            with self.assertRaises(EnvelopeError): self.decode(e)

    def test_inner_task_and_nonce_fail_closed(self):
        for field in ['t', 'n']:
            b = {'t': self.task, 'n': self.nonce, 's': 'DUMMY'}; b[field] = 'different'
            with self.assertRaises(EnvelopeError): self.decode(self.envelope(b))

    def test_malformed_ciphertext_or_extra_field_rejected(self):
        for e in [{**self.envelope(), 'ciphertext_hex': '00'}, {**self.envelope(), 'extra': 'x'}]:
            with self.assertRaises(EnvelopeError): self.decode(e)

    def test_wrong_pinned_key_rejected(self):
        with self.assertRaises(EnvelopeError): self.decode(self.envelope(), expected_key_sha256='0' * 64)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['--self-test']:
        raise SystemExit('Only --self-test is supported; real decoding must stay in caller memory.')
    unittest.main(argv=[sys.argv[0]], verbosity=2)
