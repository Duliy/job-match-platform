import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from crawler_sources import crawl_source,normalize_job,canonical_link,search_url
import login_helper


def snapshot(page,total=3,n=30):
    return dict(jobs=[dict(title='岗位'+str(i),company='公司',area='深圳',education='本科',
                          link='https://www.liepin.com/job/{}-{}.shtml?curPage={}'.format(page,i,page),page=page)
                      for i in range(n)],page=page,total_pages=total,has_next=page<total,empty=False,blocked='')


class Browser:
    def __init__(self,pages):self.pages=pages;self.index=0;self.visits=[]
    def get(self,url):self.visits.append(url)
    def execute_script(self,script,*args):
        if 'const text=' in script:return copy.deepcopy(self.pages[self.index])
        self.index=min(self.index+1,len(self.pages)-1);return True


class SourceCrawlerTests(unittest.TestCase):
    def test_all_cards_and_all_pages_are_saved(self):
        driver=Browser([snapshot(i) for i in (1,2,3)]);report={};batches=[]
        jobs=crawl_source(driver,'信息管理','liepin',report=report,on_page=lambda b:batches.append(len(b)),page_delay=0)
        self.assertEqual(90,len(jobs));self.assertEqual([30,30,30],batches)
        self.assertTrue(report['complete']);self.assertEqual(3,report['pages'])
        self.assertTrue(all('?' not in j['链接'] for j in jobs))

    def test_page_limit_stops_without_clicking_next(self):
        driver=Browser([snapshot(i,total=60,n=1) for i in range(1,61)]);report={}
        jobs=crawl_source(driver,'测试','liepin',max_pages=50,report=report,page_delay=0)
        self.assertEqual(50,len(jobs));self.assertEqual(49,driver.index)
        self.assertEqual('达到配置页数上限',report['reason'])

    def test_validation_wall_preserves_previous_page_and_stops(self):
        driver=Browser([snapshot(1),dict(snapshot(2),jobs=[],blocked='安全验证/访问限制')]);report={};saved=[]
        jobs=crawl_source(driver,'测试','liepin',report=report,on_page=lambda b:saved.extend(b),page_delay=0)
        self.assertEqual(30,len(jobs));self.assertEqual(jobs,saved)
        self.assertFalse(report['complete']);self.assertIn('安全验证',report['reason'])
        self.assertEqual(1,len(driver.visits))

    def test_repeated_page_is_not_misreported_as_success(self):
        driver=Browser([snapshot(1),snapshot(1)]);report={}
        crawl_source(driver,'测试','liepin',report=report,page_delay=0,timeout=.001)
        self.assertFalse(report['complete']);self.assertEqual(1,report['pages'])
        self.assertIn('重复',report['reason'])

    def test_unknown_pagination_is_not_a_completed_result(self):
        report={};driver=Browser([dict(snapshot(1),has_next=None,total_pages=None)])
        crawl_source(driver,'测试','liepin',report=report,page_delay=0)
        self.assertFalse(report['complete']);self.assertIn('分页控件',report['reason'])

    def test_empty_result_requires_explicit_empty_state(self):
        report={};driver=Browser([dict(snapshot(1),jobs=[],empty=True)])
        self.assertEqual([],crawl_source(driver,'测试','liepin',report=report,page_delay=0))
        self.assertTrue(report['complete']);self.assertEqual(0,report['pages'])

    def test_daily_salary_and_hidden_characters_are_not_fabricated(self):
        job=normalize_job(dict(title='\ue001营销',minsalary=100,maxsalary=150),'市场','shixiseng')
        self.assertEqual('100-150元/天',job['薪资'])
        self.assertIn('完整职位名见原站',job['职位名称']);self.assertNotIn('\ue001',job['职位名称'])
        self.assertEqual('面议',normalize_job(dict(title='实习',minsalary=0,maxsalary=0),'测试','shixiseng')['薪资'])

    def test_tracking_ids_do_not_create_duplicates_and_search_is_encoded(self):
        self.assertEqual(canonical_link('https://www.liepin.com/job/1.shtml?index=1'),canonical_link('https://www.liepin.com/job/1.shtml?index=2'))
        self.assertIn('curPage=1',search_url('liepin','a & b',2))
        self.assertIn('key=a+%26+b',search_url('liepin','a & b',2))

    def test_source_failures_are_persisted_without_hiding_healthy_sources(self):
        def crawl(driver,keyword,platform,**kwargs):
            kwargs['report'].update(complete=platform=='liepin',reason='需要登录' if platform=='zhaopin' else '已到末页',count=0)
            return []
        with tempfile.TemporaryDirectory() as folder,patch.object(login_helper,'DATA_DIR',folder), \
             patch.object(login_helper,'COOKIE_DIR',folder),patch('crawler_sources.crawl_source',side_effect=crawl):
            report={};login_helper.crawl_with_cookies(None,'测试',['liepin','zhaopin'],report=report)
            self.assertFalse(report['complete']);self.assertTrue(report['sources']['liepin']['complete'])
            self.assertTrue(Path(folder,'source_status.json').exists())
            self.assertIn('zhaopin',report['reason'])

    def test_admin_health_returns_independent_source_status(self):
        import asyncio,json,admin_api
        with tempfile.TemporaryDirectory() as folder,patch.object(login_helper,'DATA_DIR',folder), \
             patch.object(admin_api.scheduler,'DATA_DIR',folder), \
             patch.object(admin_api,'get_stats',return_value={}), \
             patch.object(admin_api.scheduler,'status',return_value={'social':{},'gk':{},'subscription':{}}):
            Path(folder,'source_status.json').write_text(json.dumps({'liepin':{'complete':True}}))
            result=asyncio.run(admin_api.health({'role':'admin'}))
            self.assertTrue(result['sources']['liepin']['complete'])

    def test_zhaopin_pagination_is_not_limited_to_first_25_cards(self):
        driver=Browser([snapshot(i,total=4,n=40) for i in range(1,5)]);report={}
        jobs=crawl_source(driver,'测试','zhaopin',report=report,page_delay=0)
        self.assertEqual(160,len(jobs));self.assertEqual(4,report['pages']);self.assertTrue(report['exhausted'])

    def test_saved_cookie_is_an_optional_login_fallback(self):
        def crawl(driver,keyword,platform,**kwargs):
            complete=crawl_mock.call_count==2
            kwargs['report'].update(complete=complete,reason='已到末页' if complete else '需要登录',count=0)
            return []
        with tempfile.TemporaryDirectory() as folder,patch.object(login_helper,'DATA_DIR',folder), \
             patch.object(login_helper,'COOKIE_DIR',folder),patch.object(login_helper,'load_cookies') as load, \
             patch('crawler_sources.crawl_source',side_effect=crawl) as crawl_mock:
            Path(folder,'liepin.json').write_text('[]')
            report={};login_helper.crawl_with_cookies(None,'测试',['liepin'],report=report)
            load.assert_called_once();self.assertEqual(2,crawl_mock.call_count)
            self.assertTrue(report['complete']);self.assertEqual('saved_cookie',report['sources']['liepin']['auth_mode'])

    def test_existing_tracked_links_are_updated_instead_of_reimported_as_new_jobs(self):
        import json,sqlite3,import_data
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder,'jobs.json')
            with patch.object(import_data,'JOBS_JSON',str(path)):
                conn=sqlite3.connect(':memory:')
                old={'职位名称':'旧名称','公司名称':'公司','来源平台':'猎聘网','工作地点':'深圳',
                     '链接':'https://www.liepin.com/job/123.shtml?curPage=0','关键词':'市场','薪资':'面议'}
                path.write_text(json.dumps({'jobs':[old]}))
                self.assertEqual(1,import_data.import_jobs_incremental(conn))
                new=dict(old,职位名称='新职位全名',工作地点='深圳-福田区',链接='https://www.liepin.com/job/123.shtml',关键词='营销')
                path.write_text(json.dumps({'jobs':[new]}))
                self.assertEqual(0,import_data.import_jobs_incremental(conn))
                row=conn.execute('select title,location,keywords from jobs').fetchone()
                self.assertEqual(('新职位全名','深圳-福田区','市场,营销'),row)
                self.assertEqual(login_helper.job_identity(old),login_helper.job_identity(new))
                conn.close()
