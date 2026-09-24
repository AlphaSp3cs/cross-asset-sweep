import asyncio, json, ssl, sys

ID1 = "zeusmobile1"
SEC1 = "xE1I80tp"
LONG = "3DoyG8lki3ihOpMkfaxBj2oHmJ2uv4xxOch0HmkIaFY"

async def test():
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    print("=== WebSocket auth on deribit.com ===\n")
    print(f"Credentials: {ID1} / {SEC1} / {LONG}\n")
    
    for client_id, client_secret, label in [
        (ID1, SEC1, "zeusmobile1/xE1I80tp"),
        (ID1, LONG, "zeusmobile1/LONG"),
        (LONG, SEC1, "LONG/xE1I80tp"),
        (LONG, "", "LONG/empty"),
        ("", LONG, "empty/LONG"),
    ]:
        print(f"Testing: {label}")
        try:
            import websockets
            async with websockets.connect(
                'wss://deribit.com/ws/v2/',
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
                auth_json = json.dumps(auth_msg)
                await ws.send(auth_json)
                print(f"  Auth sent: {client_id=}, {client_secret[:30] if client_secret else 'empty'}...")
                
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=10)
                    result = json.loads(resp)
                    print(f"  Response: {resp[:300]}")
                    
                    if 'result' in result and result['result'].get('access_token'):
                        token = result['result']['access_token']
                        print(f"  ✅ AUTH SUCCESS! Token: {token[:50]}...")
                        
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
                        print(f"  Book: {book_resp[:300]}")
                        
                        if 'result' in book_result:
                            items = book_result['result']
                            print(f"  ✅ {len(items)} instruments")
                            
                            call_oi = sum((i.get('open_interest') or 0) for i in items if i.get('option_type')=='call')
                            put_oi = sum((i.get('open_interest') or 0) for i in items if i.get('option_type')=='put')
                            
                            if call_oi > 0 and put_oi > 0:
                                ratio = put_oi / call_oi
                                print(f"\n  📊 BTC OPTIONS P/C RATIO: {ratio:.4f}")
                                print(f"     Calls OI: {call_oi:,.2f}")
                                print(f"     Puts OI: {put_oi:,.2f}")
                                print(f"     Total OI: {call_oi + put_oi:,.2f}")
                            else:
                                print(f"  ℹ️  OI data: calls={call_oi}, puts={put_oi}")
                                for inst in items[:3]:
                                    print(f"     {inst.get('instrument_name')}: OI={inst.get('open_interest')}, calls={inst.get('call_bid')}/{inst.get('call_ask')}, puts={inst.get('put_bid')}/{inst.get('put_ask')}")
                        return token
                    
                    elif 'error' in result:
                        code = result['error'].get('code', '?')
                        msg = result['error'].get('message', '')
                        print(f"  ❌ Auth error {code}: {msg}")
                    else:
                        print(f"  Unexpected response")
                except asyncio.TimeoutError:
                    print(f"  ⏱ Timeout waiting for response")
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
        print()
    
    # Password grant type
    print("\n=== Password grant type ===\n")
    for client_id, client_secret, label in [
        (ID1, SEC1, "zeusmobile1/xE1I80tp"),
        (ID1, LONG, "zeusmobile1/LONG"),
        (LONG, SEC1, "LONG/xE1I80tp"),
    ]:
        print(f"Testing: {label}")
        try:
            import websockets
            async with websockets.connect(
                'wss://deribit.com/ws/v2/',
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
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                result = json.loads(resp)
                print(f"  Response: {resp[:300]}")
                
                if 'result' in result and result['result'].get('access_token'):
                    print(f"  ✅ PASSWORD AUTH SUCCESS!")
                    return result['result']['access_token']
                elif 'error' in result:
                    print(f"  ❌ {result['error'].get('code')}: {result['error'].get('message')}")
        except Exception as e:
            print(f"  ❌ {type(e).__name__}")
        print()
    
    # Try with deribit.com testnet
    print("\n=== Testnet WebSocket ===\n")
    for client_id, client_secret, label in [
        (ID1, SEC1, "zeusmobile1/xE1I80tp"),
        (ID1, LONG, "zeusmobile1/LONG"),
        (LONG, SEC1, "LONG/xE1I80tp"),
    ]:
        print(f"Testing: {label}")
        try:
            import websockets
            async with websockets.connect(
                'wss://testnet.deribit.com/ws/v2/',
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
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                result = json.loads(resp)
                print(f"  Response: {resp[:300]}")
                
                if 'result' in result and result['result'].get('access_token'):
                    print(f"  ✅ TESTNET AUTH SUCCESS!")
                    return result['result']['access_token']
                elif 'error' in result:
                    print(f"  ❌ {result['error'].get('code')}: {result['error'].get('message')}")
        except Exception as e:
            print(f"  ❌ {type(e).__name__}")
        print()
    
    print("\n=== COMPLETE ===")

asyncio.run(test())
