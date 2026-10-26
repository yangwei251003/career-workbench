"""Real browser acceptance against an isolated temporary data directory.

Playwright is a development-only dependency already available on this computer.
The delivered app does not require it. No production records are changed.
"""
from pathlib import Path
import json
import sys
import tempfile
import threading
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server
from playwright.sync_api import sync_playwright, expect


def run():
    checks, errors, external = [], [], []
    catalog = server.read_json(ROOT / 'catalog/catalog.json')
    seed = server.read_json(ROOT / 'catalog/seed.json')
    report = ROOT / 'qa/浏览器实测.json'
    with tempfile.TemporaryDirectory(prefix='career-ui-中文路径 ') as temp:
        temp = Path(temp)
        store = server.Store(catalog, seed, temp / 'data')
        httpd = server.create_server('127.0.0.1', 0, store, catalog)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1,permissions=['clipboard-read','clipboard-write'],accept_downloads=True)
            page = context.new_page()
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda req:external.append(req.url) if not req.url.startswith(base) and not req.url.startswith(('blob:','data:')) else None)

            def ok(label):
                checks.append({'case':label,'status':'PASS'})
                print('PASS',label,flush=True)

            def nav(name):
                page.locator(f'#navigation a[href="#{name}"]').click()
                expect(page.locator('#main h1')).to_be_visible()

            def fill_record(collection, values):
                page.locator(f'[data-action="add-record"][data-collection="{collection}"]').first.click()
                for field,value in values.items():
                    element = page.locator(f'#edit-{field}')
                    if element.evaluate('(el)=>el.tagName') == 'SELECT':
                        element.select_option(value)
                    else:
                        element.fill(value)
                page.get_by_role('button',name='保存记录',exact=True).click()
                expect(page.locator('#editor-dialog')).not_to_be_visible()

            try:
                page.goto(base,wait_until='networkidle')
                expect(page.locator('#main h1')).to_contain_text('把每一次积累')
                assert len(catalog['projects']) == 40
                page.screenshot(path=str(ROOT/'qa/01_概览.png'),full_page=True)
                ok('真实浏览器加载个性化首页与40项目目录')
                nav('roadmap')
                expect(page.locator('.timeline-block')).to_have_count(4)
                for year in ('2027','2028','2031','2036'):
                    assert year in page.locator('.timeline').inner_text()
                ok('1/2/5/10年三情景路线完整显示')
                nav('projects')
                expect(page.locator('.project-row')).to_have_count(40)
                page.locator('#project-search').fill('课程与宣传事实中心')
                expect(page.locator('.project-row')).to_have_count(1)
                page.locator('#category-filter').select_option('B')
                expect(page.locator('.project-row')).to_have_count(0)
                page.get_by_role('button',name='清除筛选',exact=True).click()
                page.locator('#horizon-filter').select_option('10')
                expect(page.locator('.project-row')).to_have_count(sum(10 in p['horizons'] for p in catalog['projects']))
                page.get_by_role('button',name='清除筛选',exact=True).click()
                page.screenshot(path=str(ROOT/'qa/02_项目库.png'),full_page=False)
                ok('项目名称/类别/阶段组合筛选与空结果')
                page.locator('[data-action="open-project"][data-id="13"]').first.click()
                expect(page.locator('#project-dialog')).to_be_visible()
                page.get_by_role('button',name='复制 Codex 提示词',exact=True).click()
                copied = page.evaluate('navigator.clipboard.readText()')
                assert '课程与宣传事实中心' in copied and len(copied)>300
                with page.expect_download() as item:
                    page.get_by_role('button',name='下载项目卡',exact=True).click()
                card = item.value
                card.save_as(str(temp/'card.md'))
                assert '验收' in (temp/'card.md').read_text(encoding='utf-8')
                page.locator('#project-status').select_option('active')
                page.locator('#project-notes').fill('浏览器验收：先核实课程口径，再请负责人试用。')
                page.locator('#project-progress-form input[name="favorite"]').check()
                page.get_by_role('button',name='保存进度与备注',exact=True).click()
                expect(page.locator('#project-feedback')).to_contain_text('已保存')
                page.get_by_role('button',name='关闭项目详情',exact=True).click()
                page.locator('#project-filters input[name="favorite"]').check()
                assert page.locator('.project-row').filter(has_text='课程与宣传事实中心').count()==1
                page.reload(wait_until='networkidle')
                assert store.get_state()['projectStates']['13']['notes'].startswith('浏览器验收')
                ok('详情/复制提示词/下载卡片/收藏/进度持久化')
                nav('facts')
                assert len(store.get_state()['facts']) >= 2
                expect(page.locator('.conflict-block')).to_have_count(1)
                page.get_by_role('button',name='导出当前可用文案',exact=True).click()
                expect(page.locator('#toast-region')).to_contain_text('暂无可用事实')
                page.screenshot(path=str(ROOT/'qa/03_事实中心.png'),full_page=True)
                ok('原始96/112口径冲突保留且禁止作为可用底稿导出')
                current = server.dt.date.today().isoformat()
                fill_record('facts',{'subject':'验收模拟课程','field':'总学时','scope':'仅测试','value':'96','unit':'学时','status':'confirmed','source':'模拟核验记录，不是机构真实课程','sourceDate':current,'validUntil':'2099-12-31','reviewer':'测试人员','confirmedAt':current,'notes':'仅临时目录测试'})
                assert server.derive(store.get_state())['stats']['readyFacts']==1
                with page.expect_download() as item:
                    page.get_by_role('button',name='导出当前可用文案',exact=True).click()
                item.value.save_as(str(temp/'publication.md'))
                assert '验收模拟课程' in (temp/'publication.md').read_text(encoding='utf-8')
                fill_record('facts',{'subject':'验收模拟课程','field':'总学时','scope':'仅测试','value':'112','unit':'学时','status':'pending','source':'第二份模拟记录'})
                assert server.derive(store.get_state())['stats']['readyFacts']==0
                record = next(f for f in store.get_state()['facts'] if f['subject']=='验收模拟课程' and f['value']=='112')
                page.locator(f'[data-action="edit-record"][data-id="{record["id"]}"]').first.click()
                page.locator('#edit-status').select_option('retired')
                page.get_by_role('button',name='保存记录',exact=True).click()
                expect(page.locator('#editor-dialog')).not_to_be_visible()
                assert server.derive(store.get_state())['stats']['readyFacts']==1
                ok('新增确认事实/冲突阻断/退役旧说法/底稿精确排除')
                nav('evidence')
                attack = '<img src=x onerror="window.badInjection=1">浏览器实测证据'
                fill_record('evidence',{'title':attack,'category':'测试','status':'demo','contribution':'只在临时目录验证，不是真实业务成果','source':'javascript:alert(1)','boundary':'没有客户效果数据'})
                expect(page.locator('.record h3').filter(has_text='浏览器实测证据')).to_be_visible()
                assert page.evaluate('window.badInjection') is None
                assert page.locator('.records-list img').count()==0
                page.reload(wait_until='networkidle')
                assert any(r['title']==attack for r in store.get_state()['evidence'])
                if page.locator('#evidence-search').count():
                    page.locator('#evidence-search').fill('浏览器实测证据')
                    expect(page.locator('.record')).to_have_count(1)
                    page.locator('#evidence-search').fill('')
                ok('成果增改读回/刷新持久化/不执行录入HTML与危险链接')
                page.get_by_role('button',name='记录成果',exact=True).click()
                page.locator('#edit-title').fill('旧窗口保留的草稿')
                page.locator('#edit-contribution').fill('写入冲突时不丢输入')
                other=context.new_page()
                other.goto(base+'/#evidence',wait_until='networkidle')
                other.get_by_role('button',name='记录成果',exact=True).click()
                other.locator('#edit-title').fill('另一窗口先保存')
                other.locator('#edit-contribution').fill('用于验证修订冲突')
                other.get_by_role('button',name='保存记录',exact=True).click()
                expect(other.locator('#editor-dialog')).not_to_be_visible()
                page.get_by_role('button',name='保存记录',exact=True).click()
                expect(page.locator('#record-feedback')).to_contain_text('另一窗口')
                expect(page.locator('#edit-title')).to_have_value('旧窗口保留的草稿')
                page.get_by_role('button',name='读取最新记录，保留当前填写内容',exact=True).click()
                expect(page.locator('#record-feedback')).to_contain_text('已读取最新')
                page.get_by_role('button',name='保存记录',exact=True).click()
                expect(page.locator('#editor-dialog')).not_to_be_visible()
                other.close()
                ok('两窗口冲突提示、保留草稿、刷新后明确再次保存')
                nav('decisions')
                fill_record('decisions',{'title':'验收：是否扩大试用','kind':'其他','assumptions':'模拟假设','nextStep':'找一名实际使用者','reviewDate':'2027-01-01','exitCondition':'无反馈则暂停'})
                page.locator('[data-tab="reviews"]').click()
                fill_record('reviews',{'projectId':'13','date':current,'baseline':'手工比对两份材料','result':'软件检查流程可运行，业务收益尚未测量','feedback':'测试人员记录，不冒充公司反馈','nextStep':'后续由实际用户试用'})
                assert len(store.get_state()['reviews'])==1
                ok('决策与试用反馈真实保存，关联项目可追溯')
                nav('backup')
                with page.expect_download() as item:
                    page.get_by_role('button',name='下载完整备份',exact=True).click()
                backupfile=temp/'backup.json'
                item.value.save_as(str(backupfile))
                backup=json.loads(backupfile.read_text(encoding='utf-8'))
                before_count=len(backup['state']['evidence'])
                nav('evidence')
                record = next(r for r in store.get_state()['evidence'] if r['title']==attack)
                page.locator(f'[data-action="delete-record"][data-id="{record["id"]}"]').click()
                page.get_by_role('button',name='确认删除',exact=True).click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                assert len(store.get_state()['evidence'])==before_count-1
                nav('backup')
                bad=temp/'bad.json';bad.write_text('{broken',encoding='utf-8')
                page.locator('#backup-file').set_input_files(str(bad))
                expect(page.locator('#import-feedback')).to_contain_text('不是有效')
                assert len(store.get_state()['evidence'])==before_count-1
                page.locator('#backup-file').set_input_files(str(backupfile))
                expect(page.get_by_role('button',name='确认替换本机记录',exact=True)).to_be_visible()
                assert len(store.get_state()['evidence'])==before_count-1
                page.get_by_role('button',name='确认替换本机记录',exact=True).click()
                expect(page.locator('#toast-region')).to_contain_text('备份已导入')
                assert len(store.get_state()['evidence'])==before_count
                assert list(store.backups.glob('*.json'))
                ok('完整备份下载/删除/非法导入拒绝/预览不写入/确认恢复')
                for route in ('overview','roadmap','projects','evidence','facts','decisions','backup'):
                    nav(route)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                ok('七视图桌面布局无横向溢出')
                page.set_viewport_size({'width':390,'height':844})
                for route in ('overview','roadmap','projects','evidence','facts','decisions','backup'):
                    nav(route)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), route
                nav('overview')
                page.screenshot(path=str(ROOT/'qa/04_窄屏.png'),full_page=True)
                nav('projects')
                page.locator('[data-action="open-project"][data-id="13"]').first.click()
                expect(page.locator('#project-dialog')).to_be_visible()
                page.keyboard.press('Escape')
                expect(page.locator('#project-dialog')).not_to_be_visible()
                ok('390px窄屏七视图/详情与键盘关闭可用')
                assert not errors, errors
                assert not external, external
                ok('无浏览器脚本异常，无外部网络资源请求')
                report.write_text(json.dumps({'status':'PASS','browser':browser.version,'checks':checks,'scriptErrors':errors,'externalRequests':external,'dataIsolation':'TemporaryDirectory; production data untouched'},ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as exc:
                page.screenshot(path=str(ROOT/'qa/失败现场.png'),full_page=True)
                report.write_text(json.dumps({'status':'FAIL','checks':checks,'error':str(exc),'traceback':traceback.format_exc(),'scriptErrors':errors,'externalRequests':external},ensure_ascii=False,indent=2),encoding='utf-8')
                raise
            finally:
                browser.close()
                httpd.shutdown();httpd.server_close();thread.join(timeout=3)
    return checks


if __name__=='__main__':
    result=run()
    print(json.dumps({'passed':len(result)},ensure_ascii=False))
