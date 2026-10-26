"""Generate portable read-only handbook, catalog CSV and package manifest."""
from pathlib import Path
import csv
import hashlib
import html
import json
import zipfile

ROOT = Path(__file__).resolve().parent


def esc(x):
    return html.escape(str(x), quote=True)


def para(x):
    return '<p>' + esc(x).replace('\n', '<br>') + '</p>'


def listing(xs):
    return '<ul>' + ''.join('<li>' + esc(x) + '</li>' for x in xs) + '</ul>'


def build():
    catalog = json.loads((ROOT / 'catalog/catalog.json').read_text(encoding='utf-8'))
    projects = catalog['projects']
    assert len(projects) == 40 and {p['id'] for p in projects} == {f'{i:02}' for i in range(1, 41)}
    assert len({p['prompt'] for p in projects}) == 40
    source_ids = {s['id'] for s in catalog['sources']}
    required = ['audience', 'problem', 'alternatives', 'personalFit', 'trigger', 'inputs', 'outputs', 'nonGoals', 'acceptance', 'continueWhen', 'stopWhen', 'firstVersion', 'prompt']
    for p in projects:
        assert all(p.get(k) for k in required), p['id']
        assert set(p['sourceIds']) <= source_ids, p['id']
    status = {'now': '现在可用', 'conditional': '条件启动', 'blueprint': '先留蓝图', 'extend': '延续已有项目'}
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>示例用户 · 十年职业与项目手册</title><style>',
    '''*{box-sizing:border-box}body{margin:0;background:#f5f3ea;color:#253c34;font:16px/1.85 "Microsoft YaHei",sans-serif}main{max-width:1120px;margin:auto;padding:50px 30px}header{border-top:8px solid #244d3d;padding:34px 0 45px}small,.muted{color:#6b756f}h1{font-family:"SimSun",serif;font-size:clamp(32px,5vw,62px);font-weight:500;line-height:1.3;margin:16px 0}h2{margin-top:52px;border-bottom:1px solid #bdc7bd;padding-bottom:14px}h3{margin-top:22px}a{color:#27644c}p{margin:8px 0 16px}ul{padding-left:24px}.note{padding:18px 24px;background:#e7ebdf;border-left:4px solid #a7773f}.route{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.route article{padding:24px;border:1px solid #c6ccbf}.year{font-family:Georgia,serif;color:#9c6b33;font-size:34px}.tools{position:sticky;top:0;background:#f5f3ea;padding:15px 0;display:flex;gap:12px;border-bottom:1px solid #c6ccbf;z-index:1}input,select{font:inherit;padding:10px 12px;min-width:0;background:#fffdf7;border:1px solid #a8b4a7;border-radius:4px}input{flex:1}.card{margin:14px 0;background:#fffdf7;border:1px solid #d2d6c9;padding:18px 24px}.card summary{cursor:pointer;display:list-item;font-weight:600}.card summary small{display:block;font-weight:400}.card[hidden]{display:none}.tag{font-size:12px;color:#976430;font-weight:500;margin-left:12px}.card .content{border-top:1px solid #deded1;margin-top:18px;padding-top:8px}.card pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf0e7;padding:18px;font:14px/1.8 "Microsoft YaHei",sans-serif}.sources{overflow-wrap:anywhere}.skills{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.skills article{border-bottom:1px solid #ccd2c5;padding-bottom:18px}footer{margin-top:50px;border-top:2px solid #244d3d;padding:24px 0;font-size:14px}@media(max-width:650px){main{padding:24px 16px}.route,.skills{grid-template-columns:1fr}.tools{flex-wrap:wrap}input{width:100%;flex-basis:100%}.card{padding:16px}}@media print{.tools{position:static}.card{break-inside:avoid}header{padding:15px 0}a{color:inherit}.route{display:block}.route article{margin-bottom:15px}}''',
    '</style></head><body><main><header><small>CAREER FIELD NOTES / 公开演示版 / 2026—2036</small><h1>成长有方向，<br>选择有余地。</h1><p>技术销售主线 · 稳定收入优先 · 1 / 2 / 5 / 10 年多情景路线</p><div class="note">这是一份离线只读手册，40张卡是备选项目蓝图。需要保存进度、成果与课程事实时，请先下载完整源码，再运行仓库根目录的 <strong>启动工作台.cmd</strong>。当前已开发本地工作台与事实中心，不代表40个产品均已完成。</div></header>',
    '<h2>你的长期主线</h2>', para(catalog['profile']['positioning']), listing(catalog['profile']['principles']),
    '<p><a href="docs/十年职业路线.md">完整职业规划文档</a> · <a href="docs/项目总索引.md">40项目文档索引</a> · <a href="README.md">使用与备份说明</a></p>',
    '<h2>四个观察点，三种情景</h2><div class="route">']
    for r in catalog['roadmap']:
        parts += [f'<article><span class="year">{esc(r["year"])}</span><h3>{esc(r["horizon"])}年后 · {esc(r["title"])}</h3>', '<strong>最好情景</strong>', para(r['best']), '<strong>基准情景</strong>', para(r['baseline']), '<strong>压力情景</strong>', para(r['stress']), '<strong>调整方式</strong>', para(r['response']), '</article>']
    parts += ['</div><h2>值得观察的机会</h2>']
    for o in catalog['opportunities']:
        parts += [f'<h3>{esc(o["title"])}</h3>', para('已有依据：' + o['evidence']), para('推断与适配：' + o['inference']), listing(o['signals']), para('边界：' + o['risk'])]
    parts += ['<h2>40个项目，按条件选择</h2><p>“现在可用”表示可以做小版本，并非这些产品都已经完成。先看启动条件，再决定是否投入。</p><div class="tools"><input id="search" aria-label="搜索项目" placeholder="搜索项目、问题、使用场景…"><select id="category" aria-label="项目类别"><option value="">全部八类</option>']
    for key in 'ABCDEFGH':
        p = next(x for x in projects if x['category'] == key)
        parts += [f'<option value="{key}">{key} · {esc(p["categoryName"])}</option>']
    parts += ['</select><select id="stage" aria-label="开发条件"><option value="">全部开发条件</option>']
    parts += [f'<option value="{k}">{v}</option>' for k, v in status.items()]
    parts += ['</select><span id="count" aria-live="polite">40 项</span></div>']
    for p in projects:
        parts += [f'<details class="card" data-category="{p["category"]}" data-stage="{p["readiness"]}"><summary>{p["id"]} / {esc(p["name"])}<span class="tag">{status[p["readiness"]]}</span><small>{esc(p["categoryName"])} · 适用观察点：{esc("、".join(str(h)+"年" for h in p["horizons"]))}</small></summary><div class="content">']
        for key, label in [('audience','目标用户'),('problem','具体问题'),('alternatives','现有替代方案'),('personalFit','与你的关系'),('trigger','启动条件'),('firstVersion','首版范围'),('inputs','输入'),('outputs','输出'),('nonGoals','首版不做'),('acceptance','验收'),('continueWhen','继续条件'),('stopWhen','停止条件')]:
            parts += [f'<h3>{label}</h3>', listing(p[key]) if isinstance(p[key], list) else para(p[key])]
        parts += ['<h3>可复制的 Codex 启动提示词</h3><pre>' + esc(p['prompt']) + '</pre></div></details>']
    parts += ['<h2>持续学习，如何证明学会了</h2><div class="skills">']
    for c in catalog['capabilities']:
        parts += [f'<article><h3>{esc(c["name"])}</h3>', para(c['focus']), para('验收：' + c['proof']), '</article>']
    parts += ['</div><h2>仍需核实</h2>', listing(catalog['profile']['unknowns']), '<h2>资料与证据</h2><div class="sources">']
    for s in catalog['sources']:
        target = s.get('url', '')
        title = '<a href="' + esc(target) + '" target="_blank" rel="noopener noreferrer">' + esc(s['title']) + '</a>' if target.startswith(('http://', 'https://')) else esc(s['title'])
        parts += [f'<p><strong>{esc(s["id"])} · {title}</strong><br><small>{esc(s.get("date", ""))} / {esc(s.get("note", ""))}</small>']
        if s.get('path'):
            parts += ['<br><small>' + esc(s['path']) + '</small>']
        parts += ['</p>']
    parts += ['</div><footer>资料基点：2026-10-24。未来政策、岗位与商业机会需重新核实。<br>本文件不联网，不保存输入；可变记录请使用本地工作台。</footer></main><script>',
    '''const cards=[...document.querySelectorAll('.card')];function filter(){const q=document.getElementById('search').value.trim().toLowerCase(),c=document.getElementById('category').value,s=document.getElementById('stage').value;let n=0;cards.forEach(x=>{x.hidden=!((!q||x.textContent.toLowerCase().includes(q))&&(!c||x.dataset.category===c)&&(!s||x.dataset.stage===s));if(!x.hidden)n++});document.getElementById('count').textContent=n+' 项'}['search','category','stage'].forEach(id=>document.getElementById(id).addEventListener('input',filter));''',
    '</script></body></html>']
    (ROOT / '阅读总览.html').write_text(''.join(parts), encoding='utf-8')
    with (ROOT / 'docs/项目灵感库.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['编号','项目','类别','开发条件','适用观察点','目标用户','问题','启动条件','首版范围','继续条件','停止条件'])
        for p in projects:
            writer.writerow([p['id'],p['name'],p['categoryName'],status[p['readiness']],'/'.join(map(str,p['horizons'])),p['audience'],p['problem'],p['trigger'],p['firstVersion'],p['continueWhen'],p['stopWhen']])
    audit = {'catalogCount':len(projects),'uniqueIds':True,'uniquePrompts':True,'allRequiredFields':True,'allSourcesResolved':True,'runtimeDependencies':'Python 3.12 standard library only','sourceDate':'2026-10-24'}
    (ROOT / 'qa/内容结构检查.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    return audit


def package():
    excluded = {'data','backups','__pycache__','.git'}
    files = [p for p in ROOT.rglob('*') if p.is_file() and not excluded.intersection(p.relative_to(ROOT).parts) and p.suffix not in ('.pyc','.zip') and p.name not in ('SHA256SUMS.txt','失败现场.png')]
    manifest = ''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(ROOT).as_posix()+'\n' for p in sorted(files))
    (ROOT / 'SHA256SUMS.txt').write_text(manifest,encoding='utf-8')
    archive = ROOT.parent / 'career-workbench-v1.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(files + [ROOT / 'SHA256SUMS.txt']):
            z.write(p, '职业发展工作台/' + p.relative_to(ROOT).as_posix())
    return {'archive':str(archive),'files':len(files)+1,'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}


if __name__ == '__main__':
    import sys
    print(json.dumps(build(),ensure_ascii=False))
    if '--package' in sys.argv:
        print(json.dumps(package(),ensure_ascii=False))
