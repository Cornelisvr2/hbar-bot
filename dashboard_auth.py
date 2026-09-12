"""
dashboard_auth.py -- login via Telegram-goedkeuring + sessies (fase 1b).

Flow:
1. /login  -> pagina met gebruikersnaam-veld.
2. POST /login/start {username} -> checkt username, maakt een 'login'-verzoek
   (telegram_webhook.nieuw_verzoek) -> stuurt Telegram-vraag met knoppen.
3. De pagina pollt /login/status?vid=... totdat 'goedgekeurd' (of geweigerd/
   verlopen). Bij goedkeuring zet de server een ondertekende sessie-cookie.
4. require_login() beschermt alle andere routes.

Sessie = ondertekende cookie (HMAC met SESSION_SECRET), geen serverstate nodig.
"""
import hashlib
import hmac
import os
import time

COOKIE_NAAM = "hbar_sessie"
SESSIE_TTL = 7 * 24 * 3600  # 7 dagen ingelogd blijven


def _secret() -> bytes:
    return os.environ.get("SESSION_SECRET", "").encode()


def _username() -> str:
    return os.environ.get("DASHBOARD_USERNAME", "")


def maak_sessie_cookie() -> str:
    """Ondertekende cookie: <vervaltijd>.<hmac>."""
    vervalt = str(int(time.time()) + SESSIE_TTL)
    handtekening = hmac.new(_secret(), vervalt.encode(), hashlib.sha256).hexdigest()
    return f"{vervalt}.{handtekening}"


def cookie_geldig(cookie: str | None) -> bool:
    if not cookie or "." not in cookie or not _secret():
        return False
    try:
        vervalt_str, handtekening = cookie.rsplit(".", 1)
    except ValueError:
        return False
    verwacht = hmac.new(_secret(), vervalt_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(verwacht, handtekening):
        return False
    try:
        return int(vervalt_str) > time.time()
    except ValueError:
        return False


def username_klopt(ingevoerd: str) -> bool:
    verwacht = _username()
    if not verwacht:
        return False
    return hmac.compare_digest(ingevoerd.strip(), verwacht)


# Simpele, zelfstandige loginpagina (geen template nodig). Vult gebruikersnaam
# in -> start verzoek -> pollt tot goedkeuring -> herlaadt naar het dashboard.
LOGIN_HTML = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HBAR-bot login</title>
<style>
 body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;display:flex;
  min-height:100vh;align-items:center;justify-content:center;margin:0}
 .kaart{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:28px;width:320px}
 h1{font-size:17px;font-weight:500;margin:0 0 4px}
 p{font-size:13px;color:#8b949e;margin:0 0 18px}
 input{width:100%;box-sizing:border-box;padding:9px 11px;border:1px solid #30363d;border-radius:7px;
  background:#0d1117;color:#e6edf3;font-size:14px;margin-bottom:10px}
 button{width:100%;padding:9px;border:none;border-radius:7px;background:#1D9E75;color:#fff;
  font-size:14px;font-weight:600;cursor:pointer}
 button:disabled{opacity:.6;cursor:default}
 .status{font-size:13px;color:#8b949e;margin-top:14px;min-height:18px;text-align:center}
 .fout{color:#f85149}
</style></head><body>
<div class="kaart">
  <h1>HBAR-bot</h1>
  <p>Log in en bevestig via Telegram.</p>
  <input id="u" placeholder="gebruikersnaam" autocomplete="username" autofocus>
  <button id="b" onclick="start()">Inloggen</button>
  <div class="status" id="s"></div>
</div>
<script>
let timer=null;
async function start(){
  const u=document.getElementById('u').value.trim();
  const b=document.getElementById('b'), s=document.getElementById('s');
  if(!u){return}
  b.disabled=true; s.className='status'; s.textContent='Verzoek verstuurd — bevestig in Telegram…';
  try{
    const r=await fetch('/login/start',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({username:u})});
    const d=await r.json();
    if(!d.ok){s.className='status fout';s.textContent=d.reden||'mislukt';b.disabled=false;return}
    poll(d.vid);
  }catch(e){s.className='status fout';s.textContent='fout: '+e;b.disabled=false}
}
function poll(vid){
  let n=0;
  timer=setInterval(async()=>{
    n++;
    if(n>40){clearInterval(timer);document.getElementById('s').textContent='verlopen — probeer opnieuw';
      document.getElementById('b').disabled=false;return}
    const r=await fetch('/login/status?vid='+vid); const d=await r.json();
    const s=document.getElementById('s');
    if(d.status==='goedgekeurd'){clearInterval(timer);s.textContent='✅ Goedgekeurd — inloggen…';
      setTimeout(()=>location.href='/',600)}
    else if(d.status==='geweigerd'){clearInterval(timer);s.className='status fout';
      s.textContent='geweigerd';document.getElementById('b').disabled=false}
    else if(d.status==='verlopen'||d.status==='onbekend'){clearInterval(timer);s.className='status fout';
      s.textContent='verlopen — probeer opnieuw';document.getElementById('b').disabled=false}
  },3000);
}
document.getElementById('u').addEventListener('keydown',e=>{if(e.key==='Enter')start()});
</script>
</body></html>"""
