"""Tests for accounts, sessions and access control.

Run against SQLite by default. Set TEST_DATABASE_URL to a PostgreSQL URL to run the same
tests against Postgres.
"""
import os
import sys
import tempfile
import time

import pytest

# Configure the app before it is imported (settings are read at import time)
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend'))
sys.path.insert(0, BACKEND)
_DATA_DIR = tempfile.mkdtemp(prefix='qc_test_')
os.environ['DATA_DIR'] = _DATA_DIR
os.environ['INVITE_CODE'] = 'let-me-in'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['ALLOWED_ORIGINS'] = 'https://chat.example.com'
if os.getenv('TEST_DATABASE_URL'):
    os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']

from starlette.websockets import WebSocketDisconnect  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from server import auth  # noqa: E402

client = TestClient(main.app)
ORIGIN = {'Origin': 'https://chat.example.com'}
_counter = iter(range(10 ** 6))


@pytest.fixture(autouse=True)
def fresh_limits():
    for limiter in (main.ip_limiter, main.pair_limiter, main.user_limiter):
        limiter._hits.clear()


def register(name=None, password='correct horse', invite='let-me-in'):
    name = name or f'user{next(_counter)}'
    res = client.post('/api/register', json={'username': name, 'password': password, 'invite_code': invite})
    return name, res


def bearer(token):
    return {'Authorization': f'Bearer {token}'}


# ---------- passwords ----------
def test_password_hash_verifies_and_is_salted():
    first, second = auth.hash_password('s3cret-pass'), auth.hash_password('s3cret-pass')
    assert first != second
    assert auth.verify_password('s3cret-pass', first)
    assert not auth.verify_password('s3cret-pasS', first)
    assert 's3cret-pass' not in first


@pytest.mark.parametrize('stored', ['', 'garbage', 'scrypt$1$2', 'md5$1$2$3$4$5', None])
def test_verify_password_rejects_malformed_hashes(stored):
    assert not auth.verify_password('anything', stored)


# ---------- tokens ----------
def test_token_round_trip():
    signer = auth.TokenSigner('k')
    assert signer.verify(signer.issue('user-1', 60)) == 'user-1'


def test_token_rejects_tampering_expiry_and_other_keys():
    signer = auth.TokenSigner('k')
    token = signer.issue('user-1', 60)
    body, sig = token.split('.')
    forged_body = auth.TokenSigner('k').issue('user-2', 60).split('.')[0]
    assert signer.verify(f'{forged_body}.{sig}') is None       # payload swapped, old signature
    assert signer.verify(f'{body}.{sig[:-2]}AA') is None       # signature altered
    assert signer.verify(signer.issue('user-1', -1)) is None   # expired
    assert auth.TokenSigner('other').verify(token) is None     # signed with a different key
    for junk in (None, '', 'abc', 'a.b.c', 123):
        assert signer.verify(junk) is None


# ---------- validation ----------
@pytest.mark.parametrize('name', ['ab', 'a' * 25, '-alex', 'alex-', 'al<ex>', 'alexа', ' '])
def test_invalid_usernames(name):
    # too short/long, bad edge characters, markup, a Cyrillic look-alike letter, or empty
    assert auth.validate_username(auth.clean_username(name)) is not None


@pytest.mark.parametrize('name', ['alex', 'Alex Rivera', 'alex.r-1', 'a_b_c', 'X' * 24])
def test_valid_usernames(name):
    assert auth.validate_username(name) is None


def test_password_rules():
    assert auth.validate_password('short') is not None
    assert auth.validate_password('x' * 129) is not None
    assert auth.validate_password('long enough') is None


def test_rate_limiter_window():
    limiter = auth.RateLimiter(limit=2, window_seconds=1)
    assert limiter.allow('k') and limiter.allow('k')
    assert not limiter.allow('k')
    assert limiter.allow('other')
    time.sleep(1.1)
    assert limiter.allow('k')


# ---------- registration ----------
def test_registration_requires_valid_invite_code():
    _, missing = register(invite=None)
    _, wrong = register(invite='nope')
    assert missing.status_code == 403 and wrong.status_code == 403
    assert 'invite' in wrong.json()['detail'].lower()


def test_registration_success_returns_session():
    name, res = register()
    assert res.status_code == 200
    body = res.json()
    assert body['username'] == name and body['token'] and body['user_id']


def test_usernames_are_unique_ignoring_case():
    name, _ = register()
    _, dup = register(name.upper())
    assert dup.status_code == 409


def test_registration_validates_input():
    assert register('a', 'correct horse')[1].status_code == 400
    assert register('good name', 'short')[1].status_code == 400
    assert client.post('/api/register', json={'username': 'x'}).status_code == 422


# ---------- login ----------
def test_login_with_correct_and_incorrect_password():
    name, _ = register(password='right password')
    ok = client.post('/api/login', json={'username': name, 'password': 'right password'})
    assert ok.status_code == 200 and ok.json()['username'] == name
    # usernames are case-insensitive but the canonical spelling is returned
    assert client.post('/api/login', json={'username': name.upper(), 'password': 'right password'}).json()['username'] == name
    bad = client.post('/api/login', json={'username': name, 'password': 'wrong password'})
    ghost = client.post('/api/login', json={'username': 'nobody-here', 'password': 'whatever123'})
    assert bad.status_code == ghost.status_code == 401
    assert bad.json() == ghost.json()          # no hint about which names exist


def test_login_is_rate_limited():
    codes = [client.post('/api/login', json={'username': 'victim', 'password': f'guess-{i}-guess'}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]


# ---------- protected HTTP endpoints ----------
def test_upload_and_history_require_a_session():
    assert client.post('/upload?filename=a.txt', files={'file': ('a.txt', b'x')}).status_code == 401
    assert client.get('/api/history').status_code == 401
    assert client.get('/api/history', headers=bearer('forged.token')).status_code == 401

    _, res = register()
    headers = bearer(res.json()['token'])
    up = client.post('/upload?filename=a.txt', files={'file': ('a.txt', b'hello')}, headers=headers)
    assert up.status_code == 200 and up.json()['url'].startswith('uploads/')
    assert client.get('/' + up.json()['url']).text == 'hello'
    assert client.get('/api/history', headers=headers).status_code == 200


def test_upload_size_limit():
    _, res = register()
    big = b'0' * (main.MAX_UPLOAD_BYTES + 1)
    r = client.post('/upload?filename=big.bin', files={'file': ('big.bin', big)}, headers=bearer(res.json()['token']))
    assert r.status_code == 413


def test_cors_only_allows_configured_origin():
    assert client.get('/health', headers=ORIGIN).headers.get('access-control-allow-origin') == 'https://chat.example.com'
    assert 'access-control-allow-origin' not in client.get('/health', headers={'Origin': 'https://evil.example'}).headers


# ---------- websocket ----------
def test_websocket_rejects_missing_or_forged_tokens():
    for frame in ({'type': 'register'}, {'type': 'register', 'token': 'forged.token'},
                  {'type': 'register', 'username': 'someone-else'}):
        with client.websocket_connect('/ws', headers=ORIGIN) as ws:
            ws.send_json(frame)
            assert ws.receive_json()['type'] == 'auth_error'
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4401


def test_websocket_rejects_wrong_first_frame_and_foreign_origin():
    with client.websocket_connect('/ws', headers=ORIGIN) as ws:
        ws.send_json({'type': 'public_message', 'content': 'hi'})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4000
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws', headers={'Origin': 'https://evil.example'}):
            pass


def test_websocket_accepts_a_valid_session_and_uses_account_name():
    name, res = register()
    with client.websocket_connect('/ws', headers=ORIGIN) as ws:
        ws.send_json({'type': 'register', 'token': res.json()['token'], 'username': 'spoofed'})
        welcome = ws.receive_json()
        assert welcome['type'] == 'welcome' and welcome['username'] == name   # identity comes from the token
