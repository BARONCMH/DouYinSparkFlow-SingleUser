#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-user local control panel.

The browser automation and sender remain in ``backend.py``.  This process
exposes only one local workspace: one owner can keep any number of Douyin
accounts, with no login, registration, admin, subscription, or redeem-code
routes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
BACKEND_PATH = ROOT / "backend.py"
# Direct Windows mode stores everything in this folder.  The sender process is
# launched from the checked-in runtime tree so no Docker-only /app path is used.
RUNTIME_ROOT = ROOT / "runtime"
os.environ.setdefault("DSF_BASE_DIR", str(RUNTIME_ROOT))
os.environ.setdefault("DSF_CONFIG_DIR", str(ROOT / "data" / "config"))
os.environ.setdefault("DSF_LOG_DIR", str(ROOT / "data" / "logs"))
_spec = importlib.util.spec_from_file_location("single_user_backend", BACKEND_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("无法加载发送引擎")
backend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backend)

HOST = "127.0.0.1"
PORT = 18081
MAX_BODY = 1_000_000
STOP_EVENT = threading.Event()
_SCHEDULE_LOCK = threading.Lock()
_SCHEDULE_SEEN: dict[str, str] = {}


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _clean_uid(value: object) -> str:
    uid = str(value or "").strip()
    return uid if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", uid) else ""


def _account(uid: str) -> dict:
    item = next((x for x in backend.load_tasks() if str(x.get("unique_id") or "") == uid), None)
    if not item:
        return {}
    return {
        "unique_id": uid,
        "username": str(item.get("username") or uid),
        "targets": [str(x) for x in item.get("targets") or []],
        "times": [str(x) for x in item.get("times") or []],
        "settings": item.get("settings") if isinstance(item.get("settings"), dict) else {},
        "cookie_count": len(backend.load_cookies(uid)),
    }


def _accounts() -> list[dict]:
    return [_account(str(x.get("unique_id") or "")) for x in backend.load_tasks()]


def _session(uid: str = ""):
    return backend.browser.pick_for(None, uid)


def _session_image(uid: str = ""):
    session = _session(uid)
    return session.image() if session is not None else None


def _record_runs() -> list:
    try:
        return backend.load_sends(100)
    except Exception:
        return []


def _status(uid: str = "") -> dict:
    session = backend.browser.snapshot_for(None, uid)
    now = backend.now_text()
    return {
        "now": now,
        "accounts": _accounts(),
        "selected": _account(uid) if uid else {},
        "auth": session,
        "runner": backend.runner.snapshot(),
        "checker": backend.checker.snapshot(),
        "runs": _record_runs(),
        "logs": backend.tail(backend.RUN_LOG, 12000),
        "schedule": {"today": now[:10], "timezone": backend.parse_env().get("TZ", "Asia/Shanghai")},
    }


def _save_account(payload: dict) -> dict:
    uid = _clean_uid(payload.get("unique_id"))
    old_uid = _clean_uid(payload.get("orig_unique_id"))
    if not uid:
        return {"ok": False, "error": "抖音号只能使用 1-40 位字母、数字、下划线或短横线"}
    tasks = backend.load_tasks()
    existing = {str(x.get("unique_id") or "") for x in tasks}
    if uid in existing and uid != old_uid:
        return {"ok": False, "error": "这个抖音号标识已经存在，请换一个"}
    entry = next((x for x in tasks if str(x.get("unique_id") or "") == old_uid), None)
    if entry is None:
        entry = {"unique_id": uid, "username": uid, "targets": [], "times": [], "settings": {}}
        tasks.append(entry)
    entry["unique_id"] = uid
    entry["username"] = str(payload.get("username") or uid).strip()[:40] or uid
    entry["targets"] = [x.strip() for x in re.split(r"[\r\n,]+", str(payload.get("targets") or "")) if x.strip()]
    times, error = backend._parse_schedule_specs(payload.get("times") or "", "发送时间")
    if error:
        return {"ok": False, "error": error}
    entry["times"] = times
    try:
        delay_min = max(0, min(600, int(float(str(payload.get("delay_min") or 0)))))
        delay_max = max(0, min(600, int(float(str(payload.get("delay_max") or 0)))))
    except (TypeError, ValueError):
        return {"ok": False, "error": "发送间隔必须是 0-600 秒的数字"}
    if delay_max < delay_min:
        delay_min, delay_max = delay_max, delay_min
    template = str(payload.get("template") or "").strip()
    entry["settings"] = {
        "template": template,
        "delay_min": delay_min,
        "delay_max": delay_max,
        "hitokoto_types": entry.get("settings", {}).get("hitokoto_types", []),
    }
    cookie_text = str(payload.get("cookie_json") or "").strip()
    cookies = None
    if cookie_text:
        try:
            cookies = json.loads(cookie_text)
        except Exception:
            return {"ok": False, "error": "Cookie 必须是 Cookie-Editor 导出的 JSON 数组"}
        if not isinstance(cookies, list):
            return {"ok": False, "error": "Cookie 必须是 Cookie-Editor 导出的 JSON 数组"}
    backend.save_account_list(tasks, old_uid, uid)
    if cookies is not None:
        backend.save_cookies(uid, cookies)
    if old_uid and old_uid != uid:
        session = _session(old_uid)
        if session is not None:
            with session.lock:
                session.unique_id = uid
                session.owner = uid
    return {"ok": True, "message": "账号配置已保存", "account": _account(uid)}


def _schedule_loop() -> None:
    """Run configured account times without the multi-user ownership layer."""
    last_minute = ""
    while not STOP_EVENT.wait(5):
        try:
            current = backend.now_text()
            day, minute = current[:10], current[11:16]
            marker = day + " " + minute
            if marker == last_minute:
                continue
            last_minute = marker
            for task in backend.load_tasks():
                uid = str(task.get("unique_id") or "")
                if not uid or not task.get("targets"):
                    continue
                if minute not in backend.schedule_specs_today(task.get("times") or [], day):
                    continue
                key = "%s|%s|%s" % (day, minute, uid)
                with _SCHEDULE_LOCK:
                    if _SCHEDULE_SEEN.get(key):
                        continue
                    _SCHEDULE_SEEN[key] = day
                    if len(_SCHEDULE_SEEN) > 500:
                        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))
                        for old_key, old_day in list(_SCHEDULE_SEEN.items()):
                            if old_day < cutoff:
                                _SCHEDULE_SEEN.pop(old_key, None)
                if not backend.runner.running() and not backend.browser.running() and not backend.checker.running():
                    backend.runner.start(uid, source="定时")
        except Exception:
            try:
                backend.log_force("单用户定时调度异常", "single-user scheduler failed")
            except Exception:
                pass


class Handler(BaseHTTPRequestHandler):
    server_version = "DouYinSparkFlow-SingleUser/1.0"

    def log_message(self, fmt, *args):
        return

    def _send(self, body: bytes, content_type: str = "application/json; charset=utf-8", status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: object, status: int = 200):
        self._send(_json_bytes(value), status=status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            return self._send(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/state":
            uid = str((parse_qs(parsed.query).get("unique_id") or [""])[0])
            return self._json(_status(uid))
        if path == "/api/shot":
            uid = str((parse_qs(parsed.query).get("unique_id") or [""])[0])
            image = _session_image(uid)
            if not image:
                return self._send(b"", "image/png", HTTPStatus.NOT_FOUND)
            return self._send(image, "image/png")
        if path == "/api/qr":
            uid = str((parse_qs(parsed.query).get("unique_id") or [""])[0])
            image = backend.browser.qr_image(uid, None)
            if not image:
                return self._send(b"", "image/png", HTTPStatus.NOT_FOUND)
            return self._send(image, "image/png")
        if path == "/api/smsproof":
            uid = str((parse_qs(parsed.query).get("unique_id") or [""])[0])
            image = backend.browser.sms_proof_image(uid, None)
            if not image:
                return self._send(b"", "image/png", HTTPStatus.NOT_FOUND)
            return self._send(image, "image/png")
        return self._json({"ok": False, "error": "页面不存在"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path
        payload = self._body()
        if path == "/api/account/save":
            try:
                return self._json(_save_account(payload))
            except Exception as error:
                return self._json({"ok": False, "error": "保存失败：%s" % error}, 400)
        if path == "/api/account/delete":
            uid = _clean_uid(payload.get("unique_id"))
            if not uid:
                return self._json({"ok": False, "error": "缺少抖音号"}, 400)
            backend.browser.stop(uid, None)
            backend.drop_account(uid)
            return self._json({"ok": True, "message": "账号已删除"})
        if path == "/api/run":
            uid = _clean_uid(payload.get("unique_id"))
            ok, message = backend.runner.start(uid, source="手动")
            return self._json({"ok": ok, "message": message})
        if path == "/api/run/stop":
            return self._json({"ok": backend.runner.kill(), "message": "已请求停止发送任务"})
        if path == "/api/check":
            uid = _clean_uid(payload.get("unique_id"))
            ok, message = backend.checker.start(uid)
            return self._json({"ok": ok, "message": message})
        if path == "/api/check/stop":
            backend.checker.stop()
            return self._json({"ok": True, "message": "已请求停止检测"})
        if path == "/api/browser/start":
            uid = _clean_uid(payload.get("unique_id"))
            account = _account(uid)
            if not account:
                return self._json({"ok": False, "error": "请先保存账号配置"}, 400)
            ok, message = backend.browser.start(uid, account.get("username") or uid)
            return self._json({"ok": ok, "message": message})
        if path.startswith("/api/browser/"):
            uid = _clean_uid(payload.get("unique_id"))
            action = path.rsplit("/", 1)[-1]
            if action == "stop":
                backend.browser.stop(uid, None)
            elif action in ("click", "wheel", "type", "press", "goto"):
                command = {"unique_id": uid, "scopes": None}
                command.update(payload)
                backend.browser.send(action, **command)
            else:
                return self._json({"ok": False, "error": "未知浏览器操作"}, 404)
            return self._json({"ok": True, "message": "操作已提交"})
        if path == "/api/auth/phone":
            phone = re.sub(r"\D", "", str(payload.get("phone") or ""))
            if not re.fullmatch(r"1\d{10}", phone):
                return self._json({"ok": False, "error": "手机号需要是 11 位数字"}, 400)
            backend.browser.send("phone", unique_id=_clean_uid(payload.get("unique_id")), scopes=None, phone=phone)
            return self._json({"ok": True, "message": "手机号已提交"})
        if path in ("/api/auth/sms", "/api/auth/pwd", "/api/auth/text"):
            uid = _clean_uid(payload.get("unique_id"))
            command = {"unique_id": uid, "scopes": None}
            command.update(payload)
            backend.browser.send(path.rsplit("/", 1)[-1], **command)
            return self._json({"ok": True, "message": "已提交"})
        return self._json({"ok": False, "error": "接口不存在"}, HTTPStatus.NOT_FOUND)


INDEX_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DouYinSparkFlow · 单用户版</title>
<style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#182033;--muted:#687386;--line:#e2e7f0;--brand:#bd2037;--brand-soft:#fff0f2;--ok:#147a50;--bad:#b3261e;--r:12px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}button,input,textarea{font:inherit}button{border:0;border-radius:9px;padding:9px 13px;background:var(--brand);color:#fff;cursor:pointer}button.secondary{background:#eef1f6;color:#334155}button.danger{background:#a51e2e}button:disabled{opacity:.55;cursor:not-allowed}input,textarea{width:100%;border:1px solid var(--line);border-radius:9px;padding:9px 10px;background:#fff;color:var(--ink)}textarea{min-height:88px;resize:vertical}.app{max-width:1450px;margin:auto;padding:22px}.top{display:flex;align-items:center;gap:14px;margin-bottom:18px}.top h1{margin:0;font-size:22px}.top span{color:var(--muted)}.top .spacer{flex:1}.badge{padding:5px 10px;border-radius:999px;background:var(--brand-soft);color:var(--brand);font-weight:700}.grid{display:grid;grid-template-columns:285px minmax(0,1fr);gap:18px;align-items:start}.panel{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px;box-shadow:0 8px 26px #1b27400b}.panel h2{font-size:16px;margin:0 0 13px}.account-list{display:flex;flex-direction:column;gap:8px}.account{display:flex;align-items:center;gap:9px;width:100%;text-align:left;background:#fafbfe;color:var(--ink);border:1px solid var(--line)}.account.on{background:var(--brand-soft);border-color:#e68a98;color:var(--brand)}.account .dot{width:9px;height:9px;border-radius:50%;background:#aab4c5}.account .dot.good{background:#20a56e}.account b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.account small{margin-left:auto;color:var(--muted)}.account-add{width:100%;margin-top:10px;background:#fff;color:var(--brand);border:1px dashed #d37b88}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.field.full{grid-column:1/-1}.field label{display:block;font-weight:700;margin-bottom:5px}.hint{font-size:12px;color:var(--muted);font-weight:400}.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:13px}.status{padding:11px 13px;border-radius:10px;background:#f5f7fb;color:var(--muted);margin:0 0 13px;white-space:pre-wrap}.status.good{background:#edf9f3;color:var(--ok)}.status.bad{background:#fff0ef;color:var(--bad)}.auth{margin-top:16px;border-top:1px solid var(--line);padding-top:15px}.auth-tools{display:flex;gap:8px;flex-wrap:wrap}.screen{margin-top:12px;background:#10131a;border-radius:10px;min-height:180px;display:grid;place-items:center;overflow:hidden;position:relative}.screen img{display:block;max-width:100%;height:auto;cursor:crosshair}.screen.empty{color:#aeb7c7;padding:24px;text-align:center}.screen .tag{position:absolute;left:10px;top:10px;background:#000a;color:#fff;padding:3px 8px;border-radius:999px;font-size:12px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{font-size:12px;color:var(--muted)}pre{white-space:pre-wrap;word-break:break-word;max-height:300px;overflow:auto;background:#10131a;color:#d7dfeb;padding:12px;border-radius:9px;font-size:12px}.note{padding:11px 13px;border-left:4px solid var(--brand);background:var(--brand-soft);color:#762332;margin-bottom:13px;border-radius:8px}.hidden{display:none!important}@media(max-width:900px){.app{padding:13px}.grid,.columns{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.field.full{grid-column:auto}.top{align-items:flex-start;flex-wrap:wrap}.top .spacer{display:none}}
</style></head><body><main class="app">
<header class="top"><h1>DouYinSparkFlow</h1><span>单用户版 · 本机控制台</span><span class="spacer"></span><span class="badge">多抖音号</span></header>
<div class="note">这是单用户本地版本：没有登录、注册、管理员、兑换码或时长服务。数据只保存到当前运行环境，页面只监听本机地址。</div>
<div class="grid"><section class="panel"><h2>抖音账号</h2><div id="accounts" class="account-list"></div><button id="newAccount" class="account-add">＋ 新增抖音号</button></section>
<section class="panel"><h2>账号配置</h2><p id="selectedStatus" class="status">请选择一个账号，或新增账号。</p><form id="accountForm"><div class="form-grid">
<div class="field"><label>抖音号标识 <span class="hint">仅用于本地区分</span></label><input id="uid" required pattern="[A-Za-z0-9_-]{1,40}" placeholder="例如 myspark"></div>
<div class="field"><label>账号名称</label><input id="username" placeholder="例如 小明的小号"></div>
<div class="field full"><label>目标好友 <span class="hint">每行一个昵称</span></label><textarea id="targets" placeholder="好友昵称"></textarea></div>
<div class="field"><label>发送时间 <span class="hint">每行一个，如 09:00</span></label><textarea id="times" placeholder="09:00\n20:25"></textarea></div>
<div class="field"><label>消息模板</label><textarea id="template" placeholder="留空使用全局默认模板"></textarea></div>
<div class="field"><label>最小间隔（秒）</label><input id="delayMin" type="number" min="0" max="600" value="0"></div>
<div class="field"><label>最大间隔（秒）</label><input id="delayMax" type="number" min="0" max="600" value="0"></div>
<div class="field full"><label>Cookie JSON <span class="hint">粘贴后保存；留空不改已有 Cookie</span></label><textarea id="cookies" placeholder="[{&quot;name&quot;:&quot;sessionid&quot;,...}]"></textarea></div>
</div><div class="actions"><button type="submit">保存账号配置</button><button id="deleteAccount" type="button" class="danger">删除当前账号</button><button id="runAll" type="button" class="secondary">运行全部账号</button><button id="runOne" type="button" class="secondary">运行当前账号</button><button id="stopRun" type="button" class="secondary">停止发送</button></div></form>
<div class="auth"><h2>授权与检测</h2><p class="hint">推荐手动授权。下方实时画面可以直接点击操作抖音页面。</p><div class="auth-tools"><button id="startAuth">开始授权</button><button id="stopAuth" type="button" class="secondary">停止授权</button><button id="checkLogin" type="button" class="secondary">检测登录状态</button><input id="phone" inputmode="numeric" placeholder="手机号" style="max-width:150px"><button id="sendPhone" type="button" class="secondary">手机号授权</button><input id="sms" inputmode="numeric" placeholder="验证码" style="max-width:120px"><button id="sendSms" type="button" class="secondary">提交验证码</button></div><div id="authStatus" class="status">授权浏览器尚未启动</div><div id="screen" class="screen empty">点击「开始授权」后，这里会显示可操作的抖音实时画面。</div></div>
</section></div>
<div class="columns"><section class="panel"><h2>最近发送记录</h2><div id="runs" class="table-wrap"></div></section><section class="panel"><h2>运行日志</h2><pre id="logs">暂无日志</pre></section></div>
</main><script>
const $=id=>document.getElementById(id); let selected='', original='';
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function post(url,data){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})});return r.json();}
function formData(){return {orig_unique_id:original,unique_id:$('uid').value.trim(),username:$('username').value.trim(),targets:$('targets').value,times:$('times').value,template:$('template').value,delay_min:$('delayMin').value,delay_max:$('delayMax').value,cookie_json:$('cookies').value};}
function renderAccounts(list){$('accounts').innerHTML=list.length?list.map(a=>`<button class="account ${a.unique_id===selected?'on':''}" data-uid="${esc(a.unique_id)}"><i class="dot ${a.cookie_count?'good':''}"></i><b>${esc(a.username||a.unique_id)}</b><small>${a.cookie_count?'已授权':'未授权'}</small></button>`).join(''):'<p class="hint">还没有账号，点击下方新增。</p>';document.querySelectorAll('.account[data-uid]').forEach(b=>b.onclick=()=>selectAccount(b.dataset.uid));}
function fill(a){original=selected=a.unique_id||'';$('uid').value=a.unique_id||'';$('username').value=a.username||'';$('targets').value=(a.targets||[]).join('\n');$('times').value=(a.times||[]).join('\n');const s=a.settings||{};$('template').value=s.template||'';$('delayMin').value=s.delay_min??0;$('delayMax').value=s.delay_max??0;$('cookies').value='';$('selectedStatus').textContent=`${a.cookie_count||0} 项 Cookie 已保存。留空 Cookie 框不会覆盖它。`;refresh();}
async function selectAccount(uid){const d=await (await fetch('/api/state?unique_id='+encodeURIComponent(uid))).json();fill(d.selected||{});}
function statusText(a){const bits=[];if(a.message)bits.push(a.message);if(a.phase)bits.push('阶段：'+a.phase);if(a.running)bits.push('浏览器运行中');return bits.join(' · ')||'授权浏览器尚未启动';}
function renderRuns(runs){if(!runs.length){$('runs').innerHTML='<p class="hint">还没有发送记录。</p>';return;} $('runs').innerHTML='<table><thead><tr><th>时间</th><th>账号</th><th>结果</th><th>详情</th></tr></thead><tbody>'+runs.map(r=>`<tr><td>${esc(r.at||'')}</td><td>${esc(r.username||r.unique_id||'')}</td><td>${esc(r.status||'')}</td><td>${esc(r.message||'')}</td></tr>`).join('')+'</tbody></table>';}
function renderScreen(auth){const box=$('screen');if(auth.has_image){box.className='screen';box.innerHTML=`<img id="shot" src="/api/shot?unique_id=${encodeURIComponent(selected)}&t=${Date.now()}" alt="可点击的抖音实时画面"><span class="tag">画面可点击</span>`;const img=$('shot');img.onclick=e=>{const r=img.getBoundingClientRect();post('/api/browser/click',{unique_id:selected,x:Math.round((e.clientX-r.left)*img.naturalWidth/r.width),y:Math.round((e.clientY-r.top)*img.naturalHeight/r.height)});};}else{box.className='screen empty';box.textContent='点击「开始授权」后，这里会显示可操作的抖音实时画面。';}}
async function refresh(){const d=await (await fetch('/api/state?unique_id='+encodeURIComponent(selected))).json();renderAccounts(d.accounts||[]);if(d.selected&&d.selected.unique_id&&!original)fill(d.selected);$('authStatus').textContent=statusText(d.auth||{});renderScreen(d.auth||{});renderRuns(d.runs||[]);$('logs').textContent=d.logs||'暂无日志';}
$('newAccount').onclick=()=>{original=selected='';$('uid').value='';$('username').value='';$('targets').value='';$('times').value='';$('template').value='';$('delayMin').value=0;$('delayMax').value=0;$('cookies').value='';$('selectedStatus').textContent='正在新增账号。保存后即可授权。';renderAccounts([]);};
$('accountForm').onsubmit=async e=>{e.preventDefault();const r=await post('/api/account/save',formData());$('selectedStatus').textContent=r.message||r.error||'';if(r.ok){fill(r.account);}refresh();};
$('deleteAccount').onclick=async()=>{if(!selected||!confirm('确定删除当前账号及其 Cookie 吗？'))return;const r=await post('/api/account/delete',{unique_id:selected});$('selectedStatus').textContent=r.message||r.error||'';selected=original='';refresh();};
$('runAll').onclick=async()=>{const r=await post('/api/run',{});$('authStatus').textContent=r.message||r.error||'';};$('runOne').onclick=async()=>{const r=await post('/api/run',{unique_id:selected});$('authStatus').textContent=r.message||r.error||'';};$('stopRun').onclick=async()=>{const r=await post('/api/run/stop',{});$('authStatus').textContent=r.message||r.error||'';};
$('startAuth').onclick=async()=>{const r=await post('/api/browser/start',{unique_id:selected});$('authStatus').textContent=r.message||r.error||'';};$('stopAuth').onclick=async()=>{const r=await post('/api/browser/stop',{unique_id:selected});$('authStatus').textContent=r.message||r.error||'';};$('checkLogin').onclick=async()=>{const r=await post('/api/check',{unique_id:selected});$('authStatus').textContent=r.message||r.error||'';};$('sendPhone').onclick=async()=>{const r=await post('/api/auth/phone',{unique_id:selected,phone:$('phone').value});$('authStatus').textContent=r.message||r.error||'';};$('sendSms').onclick=async()=>{const r=await post('/api/auth/sms',{unique_id:selected,code:$('sms').value});$('authStatus').textContent=r.message||r.error||'';};
setInterval(refresh,1500);refresh();
</script></body></html>'''


def main() -> int:
    backend.os.umask(0o077)
    threading.Thread(target=_schedule_loop, name="single-user-scheduler", daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("单用户面板已启动：http://%s:%d" % (HOST, PORT), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        STOP_EVENT.set()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
