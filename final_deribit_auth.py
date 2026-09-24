#!/usr/bin/env python3
"""Deribit auth: REST /auth/login + WebSocket, all credential combos."""
import urllib.request, json, ssl, base64, asyncio
import http.cookiejar

ID1 = "zeusmobile1"
SEC1 = "xE1I80tp"
LONG = "3DoyG8lki3ihOpMkfaxBj2oHmJ2uv4xxOch0HmkIaFY"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

print(f"Credentials: {ID1} / {SEC1} / {LONG}\n")
print("=" * 60)
print("PART 1: REST /auth/login")
print("=" * 60)

rest_success = False
rest_token = None

cj = http.cookiejar.CookieJar()
base_opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ctx),
    urllib.request.HTTPCookieProcessor(cj)
)

for email, password, label in [
    (ID1, SEC1, "zeusmobile1 / xE1I80tp"),
    (ID1, LONG, "zeusmobile1 / LONG"),
    (LONG, SEC1, "LONG / xE1I80tp"),
    (LONG, "", "LONG / empty"),
    (f"{ID1}@deribit.com", SEC1, "zeusmobile1@deribit.com / xE1I80tp"),
    (f"{ID1}@deribit.com", LONG, "zeusmobile1@deribit.com / LONG"),
]:
    print(f"\nTrying: {label}")
    
    for base_url in [
        "https://www.deribit.com/api/v2/auth/login",
        "https://www.deribit.com/auth/login",
    ]:
        login_data = json.dumps({"email": email, "password": password}).encode()
        req = urllib.request.Request(
            base_url, data=login_data, method="POST",
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.derebit.com",
                "Referer": "https://www.derebit.com/login",
            }
        )
        
        try:
            with base_opener.open(req, timeout=10) as r:
                resp_bytes = r.read()
                resp = resp_bytes.decode("utf-8", errors="replace")
                status = r.status
            
            print(f"  {base_url}: HTTP {status}, {len(resp)} chars")
            
            try:
                resp_json = json.loads(resp)
                if "access_token" in resp_json:
                    token = resp_json["access_token"]
                    print(f"  ✅ REST AUTH SUCCESS! Token: {token[:50]}...")
                    rest_token = token
                    rest_success = True
                    
                    # Test API calls with token
                    print(f"\n  Testing API with Bearer token...")
                    token_opener = urllib.request.build_opener(
                        urllib.request.HTTPSHandler(context=ctx),
                        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
                    )
                    
                    for endpoint in [
                        "/api/v2/private/get_profile",
                        "/api/v2/private/get_account_overview",
                        "/api/v2/private/get_book_summary",
                    ]:
                        full_url = f"https://www.deribit.com{endpoint}"
                        is_post = endpoint.endswith("get_book_summary")
                        
                        if is_post:
                            req_api = urllib.request.Request(
                                full_url, 
                                data=json.dumps({"currency": "BTC"}).encode(),
                                method="POST",
                                headers={
                                    "User-Agent": "Mozilla/5.0",
                                    "Accept": "application/json",
                                    "Content-Type": "application/json",
                                    "Authorization": f"Bearer {token}",
                                }
                            )
                        else:
                            req_api = urllib.request.Request(
                                full_url, method="GET",
                                headers={
                                    "User-Agent": "Mozilla/5.0",
                                    "Accept": "application/json",
                                    "Authorization": f"Bearer {token}",
                                }
                            )
                        
                        try:
                            with token_opener.open(req_api, timeout=10) as ra:
                                api_resp = json.loads(ra.read())
                            if "result" in api_resp:
                                print(f"  ✅ {endpoint}: SUCCESS")
                                if endpoint.endswith("get_book_summary"):
                                    items = api_resp["result"]
                                    print(f"     {len(items)} instruments")
                                    
                                    call_oi = sum((i.get("open_interest") or 0) for i in items if i.get("option_type")=="call")
                                    put_oi = sum((i.get("open_interest") or 0) for i in items if i.get("option_type")=="put")
                                    
                                    if call_oi > 0 and put_oi > 0:
                                        ratio = put_oi / call_oi
                                        print(f"\n     📊 BTC OPTIONS P/C RATIO: {ratio:.4f}")
                                        print(f"        Calls OI: {call_oi:,.2f}")
                                        print(f"        Puts OI: {put_oi:,.2f}")
                                        print(f"        Total OI: {call_oi + put_oi:,.2f}")
                                    else:
                                        print(f"     ℹ️  OI data unavailable (calls={call_oi}, puts={put_oi})")
                                        for inst in items[:5]:
                                            oi = inst.get("open_interest") or 0
                                            print(f"        {inst.get('instrument_name')}: OI={oi}")
                                elif endpoint.endswith("get_profile"):
                                    r = api_resp["result"]
                                    print(f"     Account ID: {r.get('account_id')}")
                                    print(f"     Email: {r.get('email')}")
                                    print(f"     Currency: {r.get('currency')}")
                                break
                            else:
                                print(f"  {endpoint}: {json.dumps(api_resp, indent=2)[:200]}")
                        except Exception as e:
                            code = getattr(e, 'code', '')
                            print(f"  {endpoint}: {type(e).__name__} {code}")
                    
                    break
                elif "error" in resp_json:
                    err = resp_json["error"]
                    print(f"  Error {err.get('code', '?')}: {err.get('message', '')[:100]}")
                else:
                    print(f"  Unexpected: {resp[:300]}")
            except json.JSONDecodeError:
                # Check if it's an HTML login page (credentials rejected)
                if "login" in resp.lower() and ("email" in resp.lower() or "password" in resp.lower()):
                    print(f"  ❌ Credentials rejected (returned to login page)")
                elif "invalid" in resp.lower() or "error" in resp.lower():
                    print(f"  ❌ Error response: {resp[:200]}")
                else:
                    print(f"  Non-JSON response: {resp[:200]}")
        except Exception as e:
            code = getattr(e, 'code', '')
            print(f"  {base_url}: {type(e).__name__} {code}")

print("\n" + "=" * 60)
print("PART 2: WEBSOCKET AUTH (wss://www.derebit.com/ws/api/v2)")
print("=" * 60)

async def ws_test():
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    ws_success = False
    
    for client_id, client_secret, label in [
        (ID1, SEC1, "zeusmobile1 / xE1I80tp"),
        (ID1, LONG, "zeusmobile1 / LONG"),
        (LONG, SEC1, "LONG / xE1I80tp"),
        (LONG, "", "LONG / empty"),
    ]:
        print(f"\nTrying: {label}")
        try:
            import websockets
            async with websockets.connect(
                "wss://www.deribit.com/ws/api/v2",
                ssl=ssl_ctx,
                ping_interval=5,
                close_timeout=5,
                max_size=10*1024*1024,
            ) as ws:
                auth_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "public/auth",
                    "params": {
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    }
                }
                await ws.send(json.dumps(auth_msg))
                print(f"  Auth sent")
                
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=10)
                    result = json.loads(resp)
                    print(f"  Response: {resp[:300]}")
                    
                    if "result" in result and result["result"].get("access_token"):
                        token = result["result"]["access_token"]
                        print(f"  ✅ WS AUTH SUCCESS! Token: {token[:50]}...")
                        ws_success = True
                        
                        # Get book summary
                        book_req = {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "private/get_book_summary",
                            "params": {"currency": "BTC"}
                        }
                        await ws.send(json.dumps(book_req))
                        book_resp = await asyncio.wait_for(ws.recv(), timeout=10)
                        book_result = json.loads(book_resp)
                        print(f"  Book: {book_resp[:500]}")
                        
                        if "result" in book_result:
                            items = book_result["result"]
                            print(f"  ✅ {len(items)} instruments")
                            
                            call_oi = sum((i.get("open_interest") or 0) for i in items if i.get("option_type")=="call")
                            put_oi = sum((i.get("open_interest") or 0) for i in items if i.get("option_type")=="put")
                            
                            if call_oi > 0 and put_oi > 0:
                                ratio = put_oi / call_oi
                                print(f"\n  📊 BTC OPTIONS P/C RATIO: {ratio:.4f}")
                                print(f"     Calls OI: {call_oi:,.2f}")
                                print(f"     Puts OI: {put_oi:,.2f}")
                                print(f"     Total OI: {call_oi + put_oi:,.2f}")
                            else:
                                print(f"  ℹ️  OI data: calls={call_oi}, puts={put_oi}")
                                for inst in items[:5]:
                                    oi = inst.get("open_interest") or 0
                                    print(f"     {inst.get('instrument_name')}: OI={oi}")
                        return token
                    
                    elif "error" in result:
                        code = result["error"].get("code", "?")
                        msg = result["error"].get("message", "")
                        print(f"  ❌ Auth error {code}: {msg}")
                        if code == 13004:
                            print(f"     → Credentials rejected (invalid_credentials)")
                        elif code == 13013:
                            print(f"     → Rate limit")
                        elif code == 13005:
                            print(f"     → Invalid client_id/secret")
                except asyncio.TimeoutError:
                    print(f"  ⏱ Timeout")
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
    
    # Password grant
    print("\nTrying password grant...")
    for client_id, client_secret, label in [
        (ID1, SEC1, "zeusmobile1 / xE1I80tp"),
        (ID1, LONG, "zeusmobile1 / LONG"),
        (LONG, SEC1, "LONG / xE1I80tp"),
    ]:
        print(f"\nTrying: {label} (password)")
        try:
            import websockets
            async with websockets.connect(
                "wss://www.deribit.com/ws/api/v2",
                ssl=ssl_ctx,
                ping_interval=5,
                close_timeout=5,
            ) as ws:
                auth_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "public/auth",
                    "params": {
                        "grant_type": "password",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    }
                }
                await ws.send(json.dumps(auth_msg))
                
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=10)
                    result = json.loads(resp)
                    print(f"  Response: {resp[:300]}")
                    
                    if "result" in result and result["result"].get("access_token"):
                        print(f"  ✅ PASSWORD AUTH SUCCESS!")
                        ws_success = True
                        return result["result"]["access_token"]
                    elif "error" in result:
                        print(f"  ❌ {result['error'].get('code', '?')}: {result['error'].get('message', '')[:100]}")
                except asyncio.TimeoutError:
                    print(f"  ⏱ Timeout")
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
    
    # Testnet WebSocket
    print("\nTrying testnet WebSocket...")
    for client_id, client_secret, label in [
        (ID1, SEC1, "zeusmobile1 / xE1I80tp"),
        (ID1, LONG, "zeusmobile1 / LONG"),
        (LONG, SEC1, "LONG / xE1I80tp"),
    ]:
        print(f"\nTrying: {label} (testnet)")
        try:
            import websockets
            async with websockets.connect(
                "wss://test.deribit.com/ws/v2/",
                ssl=ssl_ctx,
                ping_interval=5,
                close_timeout=5,
            ) as ws:
                auth_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "public/auth",
                    "params": {
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    }
                }
                await ws.send(json.dumps(auth_msg))
                
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=10)
                    result = json.loads(resp)
                    print(f"  Response: {resp[:300]}")
                    
                    if "result" in result and result["result"].get("access_token"):
                        print(f"  ✅ TESTNET AUTH SUCCESS!")
                        ws_success = True
                        return result["result"]["access_token"]
                    elif "error" in result:
                        print(f"  ❌ {result['error'].get('code', '?')}: {result['error'].get('message', '')[:100]}")
                except asyncio.TimeoutError:
                    print(f"  ⏱ Timeout")
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
    
    return None

ws_token = asyncio.run(ws_test())

print("\n" + "=" * 60)
print("RESULTS SUMMARY")
print("=" * 60)
print(f"REST auth: {'SUCCESS' if rest_success else 'FAILED'}")
if rest_token:
    print(f"  Token: {rest_token[:50]}...")
print(f"WebSocket auth: {'SUCCESS' if ws_token else 'FAILED'}")
if ws_token:
    print(f"  Token: {ws_token[:50]}...")

if not rest_success and not ws_token:
    print("\n❌ ALL AUTH ATTEMPTS FAILED")
    print("The provided credentials do not authenticate against Deribit.")
    print("Try: creating new API keys in Deribit dashboard (Settings → API)")
