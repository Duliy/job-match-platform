import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from crawler_51job import crawl_51job, normalize_job
import login_helper as helper


def snapshot(page, total=49):
    return dict(jobs=[dict(id=str(page), title='信息管理', company='学院', area='重庆',
                          page=page, education='本科', salary='6-8千', published='2026-10-10')],
                page=page, total_pages=total, has_next=page < total, empty=False)


class Browser:
    def __init__(self, pages):
        self.pages = pages
        self.index = 0
        self.visits = []

    def get(self, url):
        self.visits.append(url)

    def execute_script(self, script, *args):
        if "const target=arguments[0]" in script:
            return False
        if 'b.click()' in script:
            self.index = min(self.index + 1, len(self.pages) - 1)
            return True
        return copy.deepcopy(self.pages[self.index])


class CrawlTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("crawler_51job.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_all_49_pages_and_checkpoints(self):
        browser = Browser([snapshot(i) for i in range(1, 50)])
        batches, report = [], {}
        jobs = crawl_51job(browser, '信息管理与信息系统', on_page=batches.append, report=report)
        self.assertEqual((49, 49, 49), (len(jobs), len(batches), report['pages']))
        self.assertTrue(report['complete'])
        self.assertEqual(1, len(browser.visits))  # 后续页复用 SPA，无整页重载。
        self.assertTrue(jobs[-1]['链接'].endswith('/49.html'))

    def test_page_limit(self):
        report = {}
        jobs = crawl_51job(Browser([snapshot(1), snapshot(2)]), '信息', max_pages=2, report=report)
        self.assertEqual(2, len(jobs))
        self.assertEqual('达到配置页数上限', report['reason'])

    def test_duplicate_advertisement_does_not_drop_new_jobs(self):
        pages = [snapshot(1, 2), snapshot(2, 2)]
        pages[1]['jobs'].append(dict(pages[1]['jobs'][0], id='1'))
        self.assertEqual(2, len(crawl_51job(Browser(pages), '信息')))

    def test_failed_page_retries_and_retains_checkpoint(self):
        browser = Browser([snapshot(1), dict(snapshot(2), jobs=[])])
        batches, report = [], {}
        jobs = crawl_51job(browser, '信息', timeout=0.001, on_page=batches.append, report=report)
        self.assertEqual(1, len(jobs))
        self.assertEqual(1, len(batches))
        self.assertEqual(2, len(browser.visits))
        self.assertFalse(report['complete'])
        self.assertIn('第 2 页失败', report['reason'])

    def test_repeated_page_is_not_successful_completion(self):
        browser = Browser([snapshot(1), snapshot(1)])
        report = {}
        jobs = crawl_51job(browser, '信息', timeout=0.001, report=report)
        self.assertEqual(1, len(jobs))
        self.assertFalse(report['complete'])

    def test_retry_restores_target_when_site_resets_to_page_one(self):
        class ResetBrowser(Browser):
            def get(self, url):
                super().get(url)
                if len(self.visits) == 2:
                    self.pages = [snapshot(1, 2), snapshot(2, 2)]
                    self.index = 0

            def execute_script(self, script, *args):
                if "const target=arguments[0]" in script:
                    self.index = args[0] - 1
                    return True
                return super().execute_script(script, *args)

        browser = ResetBrowser([snapshot(1, 2), dict(snapshot(2, 2), jobs=[])])
        report = {}
        jobs = crawl_51job(browser, '信息', timeout=0.001, report=report)
        self.assertEqual(2, len(jobs))
        self.assertTrue(report['complete'])

    def test_empty_first_page(self):
        report = {}
        self.assertEqual([], crawl_51job(Browser([dict(snapshot(1), jobs=[], empty=True)]), '无', report=report))
        self.assertTrue(report['complete'])

    def test_fields_from_metadata(self):
        job = normalize_job(snapshot(1)['jobs'][0], '信息')
        self.assertEqual(('重庆', '本科', '2026-10-10'),
                         (job['工作地点'], job['学历要求'], job['发布日期']))

    def test_persistence_merge_locations_keywords_and_refresh(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(helper, 'DATA_DIR', folder):
            original = normalize_job(snapshot(1)['jobs'][0], '信息管理')
            other = dict(original, 链接='https://jobs.51job.com/all/2.html', 工作地点='成都')
            helper.save_results([original, other], '信息管理', export_excel=False)
            path = Path(folder) / 'jobs_latest.json'
            saved = json.loads(path.read_text())
            saved['jobs'][0]['first_seen'] = (date.today()-timedelta(days=10)).isoformat()
            path.write_text(json.dumps(saved))
            helper.save_results([dict(original, 关键词='信息系统', 薪资='8-10千')], '信息系统', export_excel=False)
            saved = json.loads(path.read_text())
            self.assertEqual(2, saved['total'])
            job = next(j for j in saved['jobs'] if j['链接'].endswith('/1.html'))
            self.assertEqual('信息管理,信息系统', job['关键词'])
            self.assertEqual('8-10千', job['薪资'])
            self.assertEqual(date.today().isoformat(), job['last_seen'])
            self.assertFalse(Path(str(path)+'.tmp').exists())

    def test_query_based_job_links_remain_distinct(self):
        base = dict(来源平台='测试', 职位名称='信息', 公司名称='学院', 工作地点='重庆')
        self.assertNotEqual(helper.job_identity(dict(base, 链接='https://example.org/job?id=1')),
                            helper.job_identity(dict(base, 链接='https://example.org/job?id=2')))

    def test_database_keeps_different_locations_and_is_idempotent(self):
        import import_data
        import sqlite3
        with tempfile.TemporaryDirectory() as folder, patch.object(helper, 'DATA_DIR', folder):
            job = normalize_job(snapshot(1)['jobs'][0], '信息')
            helper.save_results([job, dict(job, 工作地点='成都', 链接='https://jobs.51job.com/all/2.html')],
                                '信息', export_excel=False)
            with patch.object(import_data, 'JOBS_JSON', str(Path(folder)/'jobs_latest.json')):
                conn = sqlite3.connect(':memory:')
                try:
                    self.assertEqual(2, import_data.import_jobs_incremental(conn))
                    self.assertEqual(0, import_data.import_jobs_incremental(conn))
                    self.assertEqual(2, conn.execute('SELECT count(*) FROM jobs').fetchone()[0])
                finally:
                    conn.close()

    def test_company_homepage_not_used_as_job_identity(self):
        job = dict(职位名称='信息管理', 公司名称='学院', 来源平台='前程无忧',
                   链接='https://jobs.51job.com/all/co123.html', 工作地点='重庆')
        self.assertNotEqual(helper.job_identity(job), helper.job_identity(dict(job, 工作地点='成都')))


if __name__ == '__main__':
    unittest.main()
