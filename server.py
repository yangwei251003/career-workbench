"""Local career workbench. Python 3.12 standard library only."""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import io
import json
import mimetypes
import os
import re
import secrets
import threading
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

BASE = Path(__file__).resolve().parent
MAX_BODY = 5 * 1024 * 1024
APP_ID = 'career-workbench'
COLLECTIONS = ('facts', 'evidence', 'decisions', 'reviews')
FIELDS = {
    'facts': ('subject', 'field', 'scope', 'value', 'unit', 'source', 'sourceDate', 'validUntil', 'status', 'reviewer', 'confirmedAt', 'notes'),
    'evidence': ('title', 'category', 'contribution', 'source', 'boundary', 'status', 'date'),
    'decisions': ('title', 'kind', 'assumptions', 'evidence', 'nextStep', 'exitCondition', 'reviewDate', 'status', 'outcome'),
    'reviews': ('projectId', 'baseline', 'result', 'feedback', 'nextStep', 'date'),
}
ENUMS = {
    'facts': {'status': ('pending', 'confirmed', 'retired')},
    'evidence': {'status': ('documented', 'self_reported', 'pending', 'demo')},
    'decisions': {'status': ('open', 'closed'), 'kind': ('就业', '读研', '创业', '其他')},
}
REQUIRED = {'facts': ('subject', 'field', 'value', 'status'), 'evidence': ('title', 'contribution', 'status'), 'decisions': ('title', 'kind', 'status'), 'reviews': ('projectId', 'result', 'date')}
DATE_FIELDS = {'sourceDate', 'validUntil', 'confirmedAt', 'date', 'reviewDate'}
PROJECT_STATUS = ('idea', 'active', 'validated', 'paused', 'archived')
META = ('id', 'createdAt', 'updatedAt')


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def strict_json(data):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('重复的JSON字段')
            result[k] = v
        return result
    return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('非法数字')))


def valid_date(value, label):
    if not value:
        return
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise APIError(400, f'{label}须为YYYY-MM-DD日期')
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        raise APIError(400, f'{label}不是有效日期')


def text_field(value, name, max_len=20000):
    if not isinstance(value, str) or len(value) > max_len or '\x00' in value:
        raise APIError(400, f'{name}必须是长度不超过{max_len}的文本')
    return value.strip()


def project_ids(catalog):
    return {p['id'] for p in catalog['projects']}


def validate_record(collection, record, catalog, require_id=True):
    if collection not in COLLECTIONS or not isinstance(record, dict):
        raise APIError(400, '记录类型不正确')
    allowed = set(FIELDS[collection]) | set(META)
    if set(record) - allowed:
        raise APIError(400, '记录含不支持的字段')
    for key in FIELDS[collection]:
        if key in record:
            text_field(record[key], key)
        if key in REQUIRED[collection] and not record.get(key, '').strip():
            raise APIError(400, f'请填写{key}')
        if key in DATE_FIELDS and record.get(key):
            valid_date(record[key], key)
    if require_id:
        rid = record.get('id')
        if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', rid):
            raise APIError(400, '记录编号无效')
    for k in META:
        if k in record:
            text_field(record[k], k, 200)
    for key, choices in ENUMS.get(collection, {}).items():
        if record.get(key) not in choices:
            raise APIError(400, f'{key}选项无效')
    if collection == 'facts' and record.get('status') == 'confirmed':
        for k in ('source', 'reviewer', 'confirmedAt', 'validUntil'):
            if not record.get(k, '').strip():
                raise APIError(400, '确认事实须填写来源、确认人、确认日期和有效截止日期')
        if record['confirmedAt'] > dt.date.today().isoformat():
            raise APIError(400, '确认日期不能在未来')
        if record['validUntil'] < record['confirmedAt']:
            raise APIError(400, '有效截止日期不能早于确认日期')
    if collection == 'reviews' and record.get('projectId') not in project_ids(catalog):
        raise APIError(400, '反馈引用了不存在的项目')


def validate_state(state, catalog):
    if not isinstance(state, dict):
        raise APIError(400, '备份缺少记录对象')
    required = {'schemaVersion', 'revision', 'projectStates', *COLLECTIONS, 'history'}
    if set(state) != required:
        raise APIError(400, '记录结构不完整或包含不支持的字段')
    if type(state['schemaVersion']) is not int or state['schemaVersion'] != 1:
        raise APIError(400, '不支持此备份版本')
    if type(state['revision']) is not int or state['revision'] < 0:
        raise APIError(400, '记录版本无效')
    for collection in COLLECTIONS:
        records = state[collection]
        if not isinstance(records, list) or len(records) > 5000:
            raise APIError(400, '记录数量或格式无效')
        ids = set()
        for record in records:
            validate_record(collection, record, catalog)
            if record['id'] in ids:
                raise APIError(400, f'{collection}存在重复编号')
            ids.add(record['id'])
    statuses = state['projectStates']
    if not isinstance(statuses, dict) or set(statuses) - project_ids(catalog):
        raise APIError(400, '项目状态引用了不存在的项目')
    for p in statuses.values():
        if not isinstance(p, dict) or set(p) - {'status', 'favorite', 'notes', 'updatedAt'}:
            raise APIError(400, '项目状态结构无效')
        if p.get('status') not in PROJECT_STATUS or type(p.get('favorite')) is not bool:
            raise APIError(400, '项目状态或收藏值无效')
        text_field(p.get('notes', ''), '项目备注')
        text_field(p.get('updatedAt', ''), '更新时间', 200)
    history = state['history']
    if not isinstance(history, list) or len(history) > 500:
        raise APIError(400, '历史记录格式无效')
    for item in history:
        if not isinstance(item, dict) or set(item) != {'at', 'action', 'revision'}:
            raise APIError(400, '历史条目格式无效')
        text_field(item['at'], '历史时间', 200)
        text_field(item['action'], '历史动作', 1000)
        if type(item['revision']) is not int or item['revision'] < 0:
            raise APIError(400, '历史版本无效')
    if len(json_bytes(state)) > MAX_BODY - 2048:
        raise APIError(413, '记录超过5MB，请先导出归档再整理')
    return state


def norm(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').split()).casefold()


def norm_value(value):
    s = norm(value)
    if re.fullmatch(r'[+-]?\d+(\.\d+)?', s):
        try:
            return Decimal(s)
        except InvalidOperation:
            pass
    return s


def derive(state, today=None):
    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    current = today.isoformat()
    groups = {}
    for fact in state['facts']:
        if fact['status'] == 'retired' or (fact.get('validUntil') and fact['validUntil'] < current):
            continue
        key = tuple(norm(fact.get(k, '')) for k in ('subject', 'field', 'scope'))
        groups.setdefault(key, []).append(fact)
    conflicts, conflict_ids = [], set()
    for key, values in groups.items():
        if len({(norm_value(v['value']), norm(v.get('unit', ''))) for v in values}) > 1:
            ids = [v['id'] for v in values]
            conflict_ids.update(ids)
            conflicts.append({'key': '|'.join(key), 'subject': values[0]['subject'], 'field': values[0]['field'], 'scope': values[0].get('scope', ''), 'ids': ids, 'values': [v['value'] + v.get('unit', '') for v in values]})
    facts = []
    for f in state['facts']:
        flags = []
        if f['status'] == 'retired':
            flags.append('已退役')
        if f['status'] == 'pending':
            flags.append('待核实')
        if not f.get('source', '').strip():
            flags.append('缺少来源')
        if not f.get('validUntil'):
            flags.append('有效期待核实')
        elif f['validUntil'] < current:
            flags.append('已过期')
        if f['id'] in conflict_ids:
            flags.append('存在口径冲突')
        if f['status'] == 'confirmed' and (not f.get('reviewer') or not f.get('confirmedAt')):
            flags.append('确认记录不完整')
        facts.append({**f, 'flags': flags, 'ready': not flags and f['status'] == 'confirmed'})
    return {'facts': facts, 'conflicts': conflicts, 'stats': {'readyFacts': sum(f['ready'] for f in facts), 'pendingFacts': sum(f['status'] == 'pending' for f in facts), 'conflictGroups': len(conflicts), 'expiredFacts': sum('已过期' in f['flags'] for f in facts)}}


class Store:
    def __init__(self, catalog, seed, data_dir):
        self.catalog = catalog
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / 'state.json'
        self.backups = self.data_dir.parent / 'backups'
        self.lock = threading.RLock()
        if self.path.exists():
            try:
                self.state = strict_json(self.path.read_text(encoding='utf-8-sig'))
                validate_state(self.state, catalog)
            except (ValueError, APIError) as e:
                raise RuntimeError(f'记录文件无法读取，请保留原文件并从备份恢复：{self.path}；{e}') from e
        else:
            self.state = copy.deepcopy(seed)
            validate_state(self.state, catalog)
            self._atomic(self.state)

    def _atomic(self, state):
        temporary = self.path.with_name('.state-' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as f:
                f.write(json_bytes(state))
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def get_state(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def export_backup(self):
        return {'app': APP_ID, 'schemaVersion': 1, 'exportedAt': now(), 'state': self.get_state()}

    def _check_revision(self, expected):
        if type(expected) is not int or expected < 0:
            raise APIError(400, '记录修订号无效，请刷新页面')
        if expected != self.state['revision']:
            raise APIError(409, '记录已在另一窗口更新。请先保留当前输入，刷新后再保存。')

    def _commit(self, candidate, action):
        candidate['revision'] = self.state['revision'] + 1
        candidate['history'] = (self.state['history'] + [{'at': now(), 'action': action, 'revision': candidate['revision']}])[-500:]
        validate_state(candidate, self.catalog)
        self.backups.mkdir(parents=True, exist_ok=True)
        name = f"backup-{dt.datetime.now():%Y%m%d-%H%M%S}-{self.state['revision']}-{uuid.uuid4().hex[:8]}.json"
        with (self.backups / name).open('xb') as f:
            f.write(json_bytes(self.export_backup()))
            f.flush()
            os.fsync(f.fileno())
        self._atomic(candidate)
        self.state = candidate
        return self.get_state()

    def save(self, collection, record, expected_revision):
        with self.lock:
            self._check_revision(expected_revision)
            validate_record(collection, record, self.catalog, require_id=False)
            candidate = self.get_state()
            old = next((r for r in candidate[collection] if r['id'] == record.get('id')), None)
            if record.get('id') and old is None:
                raise APIError(400, '待编辑记录已不存在，请刷新')
            cleaned = {k: record.get(k, '').strip() for k in FIELDS[collection]}
            cleaned.update(id=old['id'] if old else uuid.uuid4().hex, createdAt=old.get('createdAt', now()) if old else now(), updatedAt=now())
            validate_record(collection, cleaned, self.catalog)
            if old:
                candidate[collection] = [cleaned if r['id'] == old['id'] else r for r in candidate[collection]]
            else:
                candidate[collection].append(cleaned)
            return self._commit(candidate, f"{'更新' if old else '新增'} {collection} / {cleaned.get('title', cleaned.get('subject', cleaned.get('projectId', '')))}")

    def delete(self, collection, id, expected_revision):
        with self.lock:
            self._check_revision(expected_revision)
            if collection not in COLLECTIONS:
                raise APIError(400, '记录类型不正确')
            candidate = self.get_state()
            if not any(r['id'] == id for r in candidate[collection]):
                raise APIError(404, '记录不存在')
            candidate[collection] = [r for r in candidate[collection] if r['id'] != id]
            return self._commit(candidate, f'删除 {collection} / {id}（旧记录已备份）')

    def update_project(self, id, patch, expected_revision):
        with self.lock:
            self._check_revision(expected_revision)
            if not isinstance(id, str) or id not in project_ids(self.catalog) or not isinstance(patch, dict) or set(patch) - {'status', 'favorite', 'notes'}:
                raise APIError(400, '项目编号或更新字段无效')
            candidate = self.get_state()
            previous = candidate['projectStates'].get(id, {'status': 'idea', 'favorite': False, 'notes': ''})
            candidate['projectStates'][id] = {**previous, **patch, 'updatedAt': now()}
            return self._commit(candidate, f'更新项目 {id}')

    def _validate_backup(self, backup):
        if not isinstance(backup, dict) or backup.get('app') != APP_ID or type(backup.get('schemaVersion')) is not int or backup['schemaVersion'] != 1:
            raise APIError(400, '请选择本工作台导出的V1备份文件')
        if set(backup) != {'app', 'schemaVersion', 'exportedAt', 'state'}:
            raise APIError(400, '备份结构不完整或包含不支持的字段')
        text_field(backup['exportedAt'], '导出时间', 200)
        validate_state(backup.get('state'), self.catalog)
        return backup['state']

    def preview_import(self, backup):
        state = self._validate_backup(backup)
        return {'counts': {k: len(state[k]) for k in (*COLLECTIONS, 'projectStates')}, 'message': '恢复将替换当前记录；原记录会自动另存备份。项目资料库不受影响。'}

    def restore(self, backup, expected_revision):
        with self.lock:
            self._check_revision(expected_revision)
            candidate = copy.deepcopy(self._validate_backup(backup))
            return self._commit(candidate, '从导出文件恢复记录（恢复前已自动备份）')


LABELS = {'subject': '对象', 'field': '事项', 'scope': '适用范围', 'value': '说法', 'unit': '单位', 'source': '来源', 'sourceDate': '来源日期', 'validUntil': '有效截止', 'status': '状态', 'reviewer': '确认人', 'confirmedAt': '确认日期', 'notes': '备注', 'title': '标题', 'category': '类别', 'contribution': '本人贡献', 'boundary': '证据边界', 'date': '日期', 'kind': '选择类型', 'assumptions': '假设', 'evidence': '证据', 'nextStep': '下一步', 'exitCondition': '退出条件', 'reviewDate': '复核日期', 'outcome': '结果', 'projectId': '项目', 'baseline': '使用前', 'result': '使用后', 'feedback': '反馈'}
STATUS_LABELS = {'pending': '待核实', 'confirmed': '已记录确认', 'retired': '已退役', 'documented': '已有材料支持', 'self_reported': '本人确认', 'demo': '演示/研究', 'open': '待复盘', 'closed': '已复盘'}


def md_text(value):
    s = str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]()#+.!|~-])', r'\\\1', s)


def render_markdown(state, kind='all'):
    if kind not in ('all', *COLLECTIONS):
        raise APIError(400, '导出类型无效')
    sections = COLLECTIONS if kind == 'all' else (kind,)
    out = ['# 职业发展工作台 · 记录导出', '', f'导出时间：{now()}；记录版本：{state["revision"]}', '', '状态为用户记录，不等于第三方重新验真。', '']
    for section in sections:
        out.extend([f'## {dict(facts="课程与宣传事实", evidence="职业成果证据", decisions="决策复盘", reviews="项目使用反馈")[section]}', ''])
        for item in state[section]:
            out.extend([f'### {md_text(item.get("title", item.get("subject", item.get("projectId", "记录"))))}', ''])
            for field in FIELDS[section]:
                value = STATUS_LABELS.get(item.get(field, ''), item.get(field, '')) if field == 'status' else item.get(field, '')
                out.extend([f'**{LABELS.get(field, field)}：** {md_text(value).replace(chr(10), chr(10)+chr(10))}', ''])
    return '\n'.join(out)


def csv_cell(value):
    s = str(value)
    if s.lstrip().startswith(('=', '+', '-', '@')) or s.startswith(('\t', '\r')):
        return "'" + s
    return s


def render_csv(state, kind):
    if kind not in COLLECTIONS:
        raise APIError(400, 'CSV请指定一种记录类型')
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(['编号', *[LABELS.get(f, f) for f in FIELDS[kind]]])
    for item in state[kind]:
        writer.writerow([item['id'], *[csv_cell(STATUS_LABELS.get(item.get(f, ''), item.get(f, '')) if f == 'status' else item.get(f, '')) for f in FIELDS[kind]]])
    return '\ufeff' + out.getvalue()


def publication_markdown(state, today=None):
    derived = derive(state, today)
    records = [f for f in derived['facts'] if f['ready']]
    if not records:
        raise APIError(400, '暂无可用事实。请先处理口径冲突，并补齐来源、确认人、确认日期与有效期。')
    out = ['# 当前可用事实底稿', '', '仅包含无冲突、未过期且已记录确认的条目。用于人工审阅，不代表机构批准发布。', '', f'导出时间：{now()}；已排除 {len(derived["facts"])-len(records)} 条待核实、冲突、过期或退役记录。', '']
    for f in records:
        out.extend([f'## {md_text(f["subject"])} · {md_text(f["field"])}', '', f'{md_text(f["value"])} {md_text(f.get("unit", ""))}', '', f'适用范围：{md_text(f.get("scope", ""))}', '', f'来源：{md_text(f["source"])}', '', f'确认：{md_text(f["reviewer"])} / {f["confirmedAt"]}；有效截止：{f["validUntil"]}', ''])
    return '\n'.join(out)


def project_markdown(project, state=None):
    p = project
    out = [f'# {p["id"]} · {p["name"]}', '', '项目候选与开发说明；卡片存在不代表产品已开发或业务已验证。', '']
    labels = {'audience': '目标用户', 'problem': '具体问题', 'alternatives': '现有替代方案', 'personalFit': '与你的关系', 'trigger': '启动条件', 'firstVersion': '首版范围', 'inputs': '输入', 'outputs': '输出', 'nonGoals': '首版不做', 'acceptance': '验收', 'continueWhen': '继续条件', 'stopWhen': '停止条件'}
    for key, label in labels.items():
        out.extend([f'## {label}', ''])
        value = p.get(key, '')
        out.extend([f'- {x}' for x in value] if isinstance(value, list) else [str(value)])
        out.append('')
    out.extend(['## 交给 Codex 的启动提示词', '', p.get('prompt', '')])
    return '\n'.join(out)


def create_server(host, port, store, catalog, app_dir=None):
    if host != '127.0.0.1':
        raise ValueError('此应用仅允许本机127.0.0.1')
    static_root = Path(app_dir or BASE / 'app').resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = 'CareerWorkbench/1.0'

        def log_message(self, fmt, *args):
            pass

        def headers_common(self):
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

        def send(self, payload, content_type='application/json; charset=utf-8', status=200, filename=None):
            if isinstance(payload, (dict, list)):
                payload = json_bytes(payload)
            elif isinstance(payload, str):
                payload = payload.encode('utf-8')
            self.send_response(status)
            self.headers_common()
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(payload)

        def check_host(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                raise APIError(403, '仅允许从本机工作台访问')

        def run(self, action):
            try:
                self.check_host()
                action()
            except APIError as e:
                self.send({'error': e.message}, status=e.status)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                import traceback
                traceback.print_exc()
                self.send({'error': '操作未完成，原记录保持可恢复。请查看本地运行日志。'}, status=500)

        def do_GET(self):
            self.run(self.get)

        def get(self):
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            params = parse_qs(parsed.query)
            state = store.get_state()
            if path == '/api/health':
                self.send({'app': APP_ID, 'version': '1.0.0', 'root': str(BASE), 'dataRoot': str(store.data_dir.resolve())})
            elif path == '/api/bootstrap':
                self.send({'catalog': catalog, 'state': state, 'derived': derive(state), 'token': self.server.token, 'today': dt.date.today().isoformat()})
            elif path == '/api/export':
                fmt = params.get('format', ['json'])[0]
                kind = params.get('kind', ['all'])[0]
                stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
                if fmt == 'json':
                    self.send(store.export_backup(), filename=f'career-backup-{stamp}.json')
                elif fmt == 'markdown':
                    self.send(render_markdown(state, kind), 'text/markdown; charset=utf-8', filename=f'career-{kind}-{stamp}.md')
                elif fmt == 'csv':
                    self.send(render_csv(state, kind), 'text/csv; charset=utf-8', filename=f'career-{kind}-{stamp}.csv')
                else:
                    raise APIError(400, '导出格式无效')
            elif path == '/api/facts/publication':
                self.send(publication_markdown(state), 'text/markdown; charset=utf-8', filename='current-facts.md')
            elif path == '/api/project-card':
                pid = params.get('id', [''])[0]
                project = next((p for p in catalog['projects'] if p['id'] == pid), None)
                if project is None:
                    raise APIError(404, '项目不存在')
                self.send(project_markdown(project, state), 'text/markdown; charset=utf-8', filename=f'project-{pid}.md')
            elif path.startswith('/api/'):
                raise APIError(404, '接口不存在')
            else:
                root = BASE / 'docs' if path.startswith('/docs/') else static_root
                relative = path[6:] if path.startswith('/docs/') else ('index.html' if path == '/' else path.lstrip('/'))
                file = (root / relative).resolve()
                if not file.is_relative_to(root.resolve()) or not file.is_file():
                    raise APIError(404, '文件不存在')
                if file.suffix.lower() not in ('.html', '.js', '.css', '.svg', '.ico', '.png', '.md', '.txt'):
                    raise APIError(404, '文件不可访问')
                ctype = mimetypes.guess_type(file.name)[0] or 'text/plain'
                self.send(file.read_bytes(), ctype + ('; charset=utf-8' if ctype.startswith('text/') or ctype in ('application/javascript',) else ''))

        def do_POST(self):
            self.run(self.post)

        def post(self):
            origin = self.headers.get('Origin')
            allowed_origins = (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')
            if origin is not None and origin not in allowed_origins:
                raise APIError(403, '请从工作台页面提交')
            if not secrets.compare_digest(self.headers.get('X-App-Token', ''), self.server.token):
                raise APIError(403, '页面会话已失效，请刷新后重试')
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                raise APIError(400, '提交格式必须为JSON')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise APIError(400, '请求长度无效')
            if length <= 0 or length > MAX_BODY:
                raise APIError(413, '提交内容为空或超过5MB')
            self.connection.settimeout(10)
            try:
                body = strict_json(self.rfile.read(length).decode('utf-8'))
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise APIError(400, 'JSON无法读取，请检查文件是否完整')
            if not isinstance(body, dict):
                raise APIError(400, '请求结构无效')
            path = urlsplit(self.path).path
            revision = body.get('expectedRevision')
            if path == '/api/save':
                state = store.save(body.get('collection'), body.get('record'), revision)
            elif path == '/api/delete':
                state = store.delete(body.get('collection'), body.get('id'), revision)
            elif path == '/api/project':
                state = store.update_project(body.get('id'), body.get('patch'), revision)
            elif path == '/api/import/preview':
                self.send(store.preview_import(body.get('backup')))
                return
            elif path == '/api/import':
                state = store.restore(body.get('backup'), revision)
            elif path == '/api/shutdown':
                self.send({'message': '工作台已停止，记录已保存在本机。'})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                raise APIError(404, '接口不存在')
            self.send({'state': state, 'derived': derive(state)})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.store = store
    server.token = secrets.token_urlsafe(32)
    return server


class InstanceLock:
    def __init__(self, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.file = (data_dir / '.instance.lock').open('a+b')
        self.file.seek(0)
        if not self.file.read(1):
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('此资料目录已有工作台运行，请使用启动入口打开已有实例。')

    def close(self):
        self.file.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8026)
    parser.add_argument('--data-dir', type=Path, default=BASE / 'data')
    args = parser.parse_args()
    lock = InstanceLock(args.data_dir)
    try:
        catalog = read_json(BASE / 'catalog' / 'catalog.json')
        store = Store(catalog, read_json(BASE / 'catalog' / 'seed.json'), args.data_dir)
        server = create_server('127.0.0.1', args.port, store, catalog)
        runtime = {'pid': os.getpid(), 'port': server.server_port, 'root': str(BASE), 'dataRoot': str(args.data_dir.resolve())}
        (args.data_dir / 'runtime.json').write_bytes(json_bytes(runtime))
        print(f'职业发展工作台：http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        lock.close()


if __name__ == '__main__':
    main()
