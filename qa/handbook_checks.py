from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def run():
    errors=[]
    remote=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':960})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http://','https://')) else None)
        page.goto((ROOT/'阅读总览.html').as_uri(),wait_until='load')
        expect(page.locator('.card')).to_have_count(40)
        expect(page.locator('.route article')).to_have_count(4)
        expect(page.locator('.skills article')).to_have_count(8)
        page.locator('#search').fill('课程与宣传事实中心')
        expect(page.locator('.card:visible')).to_have_count(1)
        page.locator('#category').select_option('D')
        expect(page.locator('.card:visible')).to_have_count(0)
        page.locator('#search').fill('')
        expect(page.locator('.card:visible')).to_have_count(5)
        page.locator('#category').select_option('')
        page.locator('#stage').select_option('blueprint')
        expect(page.locator('.card:visible')).to_have_count(3)
        page.locator('#stage').select_option('')
        page.locator('.card').first.locator('summary').click()
        expect(page.locator('.card').first.locator('pre')).to_contain_text('职业成果证据库')
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(ROOT/'qa/05_离线手册.png'))
        assert not errors,errors
        assert not remote,remote
        browser.close()
    report={'status':'PASS','cards':40,'roadmap':4,'capabilities':8,'searchAndFilters':'PASS','promptReadable':'PASS','scriptErrors':errors,'networkRequests':remote,'mode':'file://; no server required'}
    (ROOT/'qa/离线手册验收.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':run()
