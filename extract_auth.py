#!/usr/bin/env python3
"""Extract auth endpoints from Deribit login page JS bundle."""
import urllib.request, ssl, re, json, os, sys

ID1 = "zeusmobile1"
SEC1 = "xE1I80tp"
LONG = "3DoyG8lki3ihOpMkfaxBj2oHmJ2uv4xxOch0HmkIaFY"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

print(f"Credentials: {ID1} / {SEC1} / {LONG}\n")

# Get login page
print("=== Step 1: Get login page ===")
req = urllib.request.Request(
    "https://www.derebit.com/login",
    headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
)
with opener.open(req, timeout=15) as r:
    html = r.read().decode("utf-8", errors="replace")

print(f"Page size: {len(html)} chars")

# Find all JS URLs
js_urls = re.findall(r'src="(/[^"]*\.js[^"]*)"', html)
js_urls += re.findall(r'src="(https?://[^"]*\.js[^"]*)"', html)
print(f"\nJS URLs found: {len(js_urls)}")
for url in js_urls[:10]:
    print(f"  {url}")

# Download main JS bundles (look for chunks with 'main' or 'auth' in name)
print("\n=== Step 2: Download JS bundles ===")
bundles = []
for url in js_urls:
    if 'chunk' in url.lower() or 'main' in url.lower() or 'auth' in url.lower() or 'login' in url.lower():
        full_url = url if url.startswith('http') else f"https://www.derebit.com{url}"
        try:
            with opener.open(full_url, timeout=10) as r:
                js = r.read().decode('utf-8', errors='replace')
            bundles.append((url, js))
            print(f"  Downloaded {url}: {len(js)} chars")
        except Exception as e:
            print(f"  Failed {url}: {e}")

# Also get the page's inline script or __NEXT_DATA__
print("\n=== Step 3: Search for auth endpoints in JS ===")
all_auth_strings = set()
for url, js in bundles:
    # Find URLs/paths containing auth-related keywords
    matches = re.findall(r'"([^"]*(?:auth|login|log_in|grant|token|session|api/v2/private)[^"]*)"', js)
    for m in matches:
        all_auth_strings.add(m)
    
    # Find WebSocket URLs
    ws_matches = re.findall(r'wss?://[^\s"\']+', js)
    for m in ws_matches:
        all_auth_strings.add(m)
    
    # Find API base URLs
    api_matches = re.findall(r'https?://[^\s"\']*deribit[^\s"\']*', js)
    for m in api_matches:
        all_auth_strings.add(m)

print(f"Auth-related strings found: {len(all_auth_strings)}")
for s in sorted(all_auth_strings):
    print(f"  {s}")

# Also check __NEXT_DATA__ or window.__INITIAL_STATE__
print("\n=== Step 4: Check for embedded config/data ===")
data_match = re.search(r'__NEXT_DATA__\s*=\s*({.*?});\s*</script>', html, re.DOTALL)
if data_match:
    try:
        data = json.loads(data_match.group(1))
        print(f"__NEXT_DATA__ found: {json.dumps(data, indent=2)[:1000]}")
    except:
        print("Could not parse __NEXT_DATA__")

# Search for any config objects
for pattern_name, pattern in [
    ("config/initialState", r'window\.__[^=]+\s*=\s*({.*?});'),
    ("auth config", r'auth\s*[:=]\s*({.*?});'),
    ("API config", r'api\s*[:=]\s*({[^}]*?(?:url|endpoint|base)[^}]*});'),
]:
    matches = re.findall(pattern, html, re.DOTALL)
    if matches:
        print(f"\n{pattern_name}:")
        for m in matches[:3]:
            print(f"  {m[:500]}")

# Look for the actual auth function name
print("\n=== Step 5: Find auth function calls ===")
for func_pattern in [
    r'(?:auth|login|logIn|signIn|authenticate)\s*[({]',
    r'public/auth',
    r'client_credentials',
    r'password\s*',
]:
    matches = re.findall(func_pattern, html)
    if matches:
        print(f"  {func_pattern}: {len(matches)} matches")
        for m in set(matches):
            print(f"    {m}")

for url, js in bundles:
    for func_pattern in [r'public/auth', r'client_credentials', r'(?:auth|login|logIn)\s*\(']:
        matches = re.findall(func_pattern, js)
        if matches:
            print(f"\n  In {url}:")
            for m in set(matches):
                # Show some context
                idx = js.find(m)
                if idx > 0:
                    ctx = js[max(0,idx-50):idx+len(m)+100]
                    print(f"    ...{ctx}...")

print("\n=== Step 6: Try to identify the auth API call from the JS ===")
# The Deribit frontend typically makes a POST to /api/v2/private/log_in
# Let's search for that exact pattern
for url, js in bundles:
    if '/api/v2/private/log_in' in js or 'log_in' in js:
        print(f"  Found log_in reference in {url}")
        idx = js.find('log_in')
        if idx > 0:
            print(f"    Context: ...{js[max(0,idx-100):idx+200]}...")
    if '/api/v2/private/log_in' in html:
        print(f"  Found log_in in HTML")
        idx = html.find('/api/v2/private/log_in')
        print(f"    Context: ...{html[max(0,idx-100):idx+200]}...")

# Search for the actual WebSocket URL used
print("\n=== Step 7: Find WebSocket connection details ===")
for url, js in bundles:
    for pattern in [r'wss://[^"\')\s]+', r'new\s+WebSocket\s*\([^)]+\)', r'WebSocket\s*\(']:
        matches = re.findall(pattern, js)
        if matches:
            print(f"  In {url}:")
            for m in set(matches):
                print(f"    {m}")

print("\n=== COMPLETE ===")
