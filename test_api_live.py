#!/usr/bin/env python3
"""Quick live test of async Tuya API — run from terminal to debug."""

import asyncio
import os
import sys

# Load secrets from env or secrets.env
def load_secrets():
    env_file = os.path.join(os.path.dirname(__file__), "secrets.env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

load_secrets()

EMAIL = os.environ.get("TUYA_EMAIL")
PASSWORD = os.environ.get("TUYA_PASSWORD")
HOST = os.environ.get("TUYA_HOST", "protect-eu.ismartlife.me")
REGION = os.environ.get("TUYA_REGION", "EU")

if not EMAIL or not PASSWORD:
    print("ERROR: Set TUYA_EMAIL and TUYA_PASSWORD in secrets.env")
    sys.exit(1)


async def try_login(session, host, email, password, country_code, label=""):
    """Try a single login attempt with given params."""
    import hashlib
    import base64
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "*/*",
        "Origin": f"https://{host}",
    }

    print(f"\n{'='*60}")
    print(f"  Trying: {label} (host={host}, countryCode={country_code})")
    print(f"{'='*60}")

    # Token
    async with session.post(
        f"https://{host}/api/login/token",
        json={"countryCode": country_code, "username": email, "isUid": False},
        headers=headers,
    ) as resp:
        token_resp = await resp.json()
        if not token_resp.get("success"):
            print(f"  Token FAILED: {token_resp.get('errorCode')}: {token_resp.get('errorMsg')}")
            return False

    td = token_resp["result"]
    token = td["token"]
    pb_key = td.get("pbKey", td.get("publicKey"))

    # Encrypt
    der_bytes = base64.b64decode(pb_key)
    public_key = load_der_public_key(der_bytes)
    passwd_md5 = hashlib.md5(password.encode()).hexdigest()
    encrypted = public_key.encrypt(passwd_md5.encode(), padding.PKCS1v15())
    encrypted_hex = encrypted.hex()

    # Login
    async with session.post(
        f"https://{host}/api/private/email/login",
        json={
            "countryCode": country_code,
            "email": email,
            "passwd": encrypted_hex,
            "token": token,
            "ifencrypt": 1,
            "options": '{"group":1}',
        },
        headers=headers,
    ) as resp:
        login_resp = await resp.json()
        if login_resp.get("success"):
            result = login_resp["result"]
            print(f"  ✓ LOGIN SUCCESS!")
            print(f"    UID: {result['uid']}")
            print(f"    SID: {result['sid'][:20]}...")
            print(f"    MQTT: {result['domain']['mobileMqttsUrl']}")
            return True
        else:
            print(f"  ✗ FAILED: {login_resp.get('errorCode')}: {login_resp.get('errorMsg')}")
            return False


async def main():
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=15)

    # Try multiple host + countryCode combinations
    attempts = [
        ("protect-eu.ismartlife.me", "EU", "EU Central"),
        ("protect-eu.ismartlife.me", "1", "EU host + code 1"),
        ("protect-eu.ismartlife.me", "7", "EU host + code 7 (KZ phone)"),
        ("protect-eu.ismartlife.me", "KZ", "EU host + KZ code"),
        ("protect-we.ismartlife.me", "EU", "EU East host + EU code"),
        ("protect-we.ismartlife.me", "7", "EU East host + code 7"),
        ("a1.tuyaeu.com", "EU", "IoT EU host"),
        ("protect-us.ismartlife.me", "1", "US host + code 1"),
    ]

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for host, code, label in attempts:
            try:
                ok = await try_login(session, host, EMAIL, PASSWORD, code, label)
                if ok:
                    print(f"\n✓✓✓ WORKING COMBINATION: host={host}, countryCode={code}")
                    break
            except Exception as e:
                print(f"  ✗ EXCEPTION: {e}")

    # Also try original urllib prototype for comparison
    print(f"\n{'='*60}")
    print(f"  Trying ORIGINAL urllib prototype (for comparison)")
    print(f"{'='*60}")
    try:
        import json
        import hashlib
        import base64
        from urllib.request import Request, build_opener, HTTPCookieProcessor
        from http.cookiejar import CookieJar

        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))

        def post(host, path, data):
            body = json.dumps(data).encode()
            req = Request(f"https://{host}{path}", data=body, headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "*/*",
                "Origin": f"https://{host}",
            })
            return json.loads(opener.open(req, timeout=15).read())

        token_resp = post(HOST, "/api/login/token", {
            "countryCode": REGION, "username": EMAIL, "isUid": False
        })
        if token_resp.get("success"):
            td = token_resp["result"]
            pb_key = td.get("pbKey", td.get("publicKey"))
            der_bytes = base64.b64decode(pb_key)

            from cryptography.hazmat.primitives.asymmetric import padding as p
            from cryptography.hazmat.primitives.serialization import load_der_public_key as ldpk
            pub = ldpk(der_bytes)
            md5 = hashlib.md5(PASSWORD.encode()).hexdigest()
            enc = pub.encrypt(md5.encode(), p.PKCS1v15()).hex()

            login_resp = post(HOST, "/api/private/email/login", {
                "countryCode": REGION, "email": EMAIL,
                "passwd": enc, "token": td["token"],
                "ifencrypt": 1, "options": '{"group":1}',
            })
            if login_resp.get("success"):
                print(f"  ✓ urllib LOGIN SUCCESS! uid={login_resp['result']['uid']}")
            else:
                print(f"  ✗ urllib FAILED: {login_resp.get('errorCode')}: {login_resp.get('errorMsg')}")
        else:
            print(f"  ✗ urllib token FAILED: {token_resp}")
    except Exception as e:
        print(f"  ✗ urllib EXCEPTION: {e}")

        td = token_resp["result"]
        token = td["token"]
        pb_key = td.get("pbKey", td.get("publicKey"))
        print(f"    Token: {token[:20]}...")
        print(f"    pbKey: {pb_key[:40]}...")

        # Step 2: RSA encrypt
        print(f"\n[2] RSA encrypt MD5(password)")
        der_bytes = base64.b64decode(pb_key)
        public_key = load_der_public_key(der_bytes)
        passwd_md5 = hashlib.md5(PASSWORD.encode()).hexdigest()
        encrypted = public_key.encrypt(passwd_md5.encode(), padding.PKCS1v15())
        encrypted_hex = encrypted.hex()
        print(f"    MD5: {passwd_md5}")
        print(f"    Encrypted hex: {encrypted_hex[:40]}...")

        # Step 3: Login
        print(f"\n[3] POST https://{HOST}/api/private/email/login")
        async with session.post(
            f"https://{HOST}/api/private/email/login",
            json={
                "countryCode": REGION,
                "email": EMAIL,
                "passwd": encrypted_hex,
                "token": token,
                "ifencrypt": 1,
                "options": '{"group":1}',
            },
            headers=headers,
        ) as resp:
            login_resp = await resp.json()
            print(f"    Status: {resp.status}")
            print(f"    Success: {login_resp.get('success')}")
            if not login_resp.get("success"):
                print(f"    ERROR: {login_resp.get('errorCode')}: {login_resp.get('errorMsg')}")
                return

        result = login_resp["result"]
        sid = result["sid"]
        uid = result["uid"]
        mqtt_url = result["domain"]["mobileMqttsUrl"]
        print(f"    SID: {sid[:20]}...")
        print(f"    UID: {uid}")
        print(f"    MQTT: {mqtt_url}")

        # Step 4: Device list
        print(f"\n[4] POST https://{HOST}/api/discovery/pns/device/list")
        async with session.post(
            f"https://{HOST}/api/discovery/pns/device/list",
            json={"type": "all"},
            headers=headers,
        ) as resp:
            dev_resp = await resp.json()
            print(f"    Status: {resp.status}")
            print(f"    Success: {dev_resp.get('success')}")
            if not dev_resp.get("success"):
                print(f"    ERROR: {dev_resp.get('errorCode')}: {dev_resp.get('errorMsg')}")
                print(f"    Full response: {dev_resp}")
                # Try fallback
                print(f"\n[4b] FALLBACK: POST https://{HOST}/api/home/list")
                async with session.post(
                    f"https://{HOST}/api/home/list",
                    json={},
                    headers=headers,
                ) as resp2:
                    home_resp = await resp2.json()
                    print(f"    Success: {home_resp.get('success')}")
                    print(f"    Result: {home_resp.get('result')}")
            else:
                result = dev_resp.get("result", [])
                print(f"    Result type: {type(result).__name__}")
                if isinstance(result, list):
                    print(f"    Devices: {len(result)}")
                    for d in result[:5]:
                        print(f"      - {d.get('name', '?')} (id={d.get('id', '?')[:12]}..., category={d.get('category', '?')})")
                elif isinstance(result, dict):
                    print(f"    Keys: {list(result.keys())}")
                    for key in ["list", "devices", "data"]:
                        if key in result:
                            items = result[key]
                            print(f"    {key}: {len(items)} items")
                            for d in items[:5]:
                                print(f"      - {d.get('name', '?')} (id={d.get('id', '?')[:12]}...)")

        print("\n✓ All API calls completed successfully")


asyncio.run(main())
