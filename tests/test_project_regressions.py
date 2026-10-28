import asyncio
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import requests
import schedule
from starlette.requests import Request

import gongkao_crawler as gk
import import_data
import match_api
import match_db
import scheduler


class ProjectRegressionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.db = self.root/'jobs.db'
        conn = sqlite3.connect(self.db)
        import_data.create_tables(conn)
        conn.close()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in (import_data, match_db, scheduler):
            self.stack.enter_context(patch.object(module, 'DB_PATH', str(self.db)))
        self.stack.enter_context(patch.object(scheduler, 'DATA_DIR', str(self.root)))
        self.stack.enter_context(patch.object(scheduler, 'BACKUP_DIR', str(self.root/'backups')))
        # Keep backup outside DATA_DIR to avoid recursive directory copying.
        self.stack.enter_context(patch.object(scheduler, 'DATA_DIR', str(self.root/'data')))
        (self.root/'data').mkdir()
        self.stack.enter_context(patch.object(scheduler, 'LOG_DIR', str(self.root)))
        for attribute in ('CONFIG_FILE', 'GK_CONFIG_FILE', 'SUB_CONFIG_FILE'):
            self.stack.enter_context(patch.object(scheduler, attribute, str(self.root/(attribute+'.json'))))
        self.stack.enter_context(patch.object(scheduler, 'social_running', False))
        self.stack.enter_context(patch.object(scheduler, 'gk_running', False))
        self.stack.enter_context(patch.object(scheduler, 'sub_running', False))

    def test_incremental_import_refreshes_salary_and_keyword_search_without_duplicates(self):
        path = self.root/'jobs.json'
        job = dict(职位名称='信息管理', 公司名称='学校', 链接='https://example.org/1',
                   工作地点='重庆', 薪资='5-7千', 关键词='信息管理', 学历要求='本科')
        with patch.object(import_data, 'JOBS_JSON', str(path)):
            conn = sqlite3.connect(self.db)
            path.write_text(json.dumps({'jobs':[job]}))
            self.assertEqual(1, import_data.import_jobs_incremental(conn))
            stamp = conn.execute('SELECT updated_at FROM jobs').fetchone()[0]
            path.write_text(json.dumps({'jobs':[dict(job, 薪资='8-10千', 关键词='数据分析')]}))
            self.assertEqual(0, import_data.import_jobs_incremental(conn))
            row = conn.execute('SELECT salary_raw,keywords,updated_at FROM jobs').fetchone()
            conn.close()
        self.assertEqual(('8-10千', '信息管理,数据分析', stamp), row)
        self.assertEqual(1, match_db.query_jobs(keyword='数据分析')[1])

    def test_gk_403_remains_visible_and_is_not_treated_as_empty_success(self):
        response = requests.Response(); response.status_code = 403
        self.assertFalse(response)
        report = {}
        with patch.object(gk, 'make_request', return_value=response):
            self.assertEqual([], gk.crawl_gk_jobs('bj', '公务员', report=report))
            self.assertFalse(report['complete'])
            self.assertIn('403', report['error'])
            with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
                gk.run_crawl(['bj'], ['公务员'])

    def test_gk_partial_failure_preserves_first_page(self):
        response = requests.Response();response.status_code=200;response._content=b'page'
        report={}
        with patch.object(gk, 'make_request', side_effect=[response, None]), \
             patch.object(gk, 'get_total_pages', return_value=2), \
             patch.object(gk, 'get_total_count', return_value=2), \
             patch.object(gk, 'parse_gk_table', return_value=[{'职位ID':'1'}]), \
             patch.object(gk.time, 'sleep'):
            self.assertEqual([{'职位ID':'1'}],gk.crawl_gk_jobs('bj','公务员',report=report))
            self.assertFalse(report['complete'])

    def test_scheduler_records_nonzero_gk_exit_as_error(self):
        with patch.object(scheduler, '_run_crawler_subprocess', return_value=1), \
             patch.object(scheduler, '_sync_db', return_value=0):
            result = scheduler.run_gk_crawl(['bj'])
        self.assertFalse(result['success'])
        self.assertIn('退出码 1', scheduler.load_gk_config()['last_error'])

    def test_scheduler_retains_partial_social_count_on_error(self):
        with patch.object(scheduler, '_run_crawler_subprocess', return_value=1), \
             patch.object(scheduler, '_sync_db', return_value=17):
            self.assertFalse(scheduler.run_social_crawl(['信息'])['success'])
        cfg = scheduler.load_crawl_config()
        self.assertEqual(17,cfg['last_count'])
        self.assertTrue(cfg['last_error'])

    def test_database_import_errors_are_not_silent_zero_success(self):
        with patch.object(import_data, 'import_jobs_incremental', side_effect=sqlite3.OperationalError('locked')):
            with self.assertRaisesRegex(RuntimeError,'数据库同步失败'):
                scheduler._sync_db()

    def test_exclusive_task_rejects_concurrent_entry(self):
        entered, release = threading.Event(), threading.Event()
        calls=[]
        @scheduler.exclusive_task(threading.Lock(),'busy')
        def work():
            calls.append(1);entered.set();release.wait(2)
        thread=threading.Thread(target=work);thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual({'success':False,'message':'busy'},work())
        finally:
            release.set();thread.join(2)
        self.assertEqual(1,len(calls))

    def test_scheduled_crawl_dispatches_without_blocking_scheduler(self):
        scheduler.save_crawl_config({'enabled':True,'keywords':['信息'],'interval_hours':48})
        with patch.object(scheduler,'_sched',schedule.Scheduler()) as sched, \
             patch.object(scheduler,'_start_background') as start:
            scheduler.reload_schedules()
            sched.jobs[0].run()
            start.assert_called_once_with(scheduler.run_social_crawl,['信息'])

    def test_backup_includes_committed_wal_data(self):
        # SQLite DB is outside DATA_DIR in this isolated fixture; backup reads DB_PATH.
        source=sqlite3.connect(self.db)
        try:
            source.execute('PRAGMA journal_mode=WAL');source.execute('PRAGMA wal_autocheckpoint=0')
            source.execute("INSERT INTO jobs(title,company) VALUES('WAL岗位','学校')");source.commit()
            scheduler.backup_data()
            backups=list((self.root/'backups').glob('*/jobs.db'))
            self.assertEqual(1,len(backups))
            conn=sqlite3.connect(backups[0])
            self.assertEqual('ok',conn.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual('WAL岗位',conn.execute('SELECT title FROM jobs').fetchone()[0]);conn.close()
        finally:source.close()

    def test_new_jobs_filter_runs_before_top_salary_limit_and_handles_utc(self):
        conn=sqlite3.connect(self.db)
        conn.execute("INSERT INTO jobs(title,company,salary_max,salary_type,created_at) VALUES('旧高薪','学校',99999,'monthly',datetime('now','-3 hours'))")
        conn.execute("INSERT INTO jobs(title,company,salary_max,salary_type,created_at) VALUES('新岗位','学校',5000,'monthly',datetime('now','-10 minutes'))")
        conn.commit();conn.close()
        checkpoint=(datetime.now()-timedelta(hours=1)).isoformat(' ')
        jobs=match_db.pre_filter(max_candidates=1,updated_after=checkpoint)
        self.assertEqual(['新岗位'],[j['title'] for j in jobs])

    def test_cache_separates_users_and_structured_resumes_and_reuses_valid_result(self):
        req=Request({'type':'http','headers':[(b'x-user-api-key',b'test-key')]})
        ai=AsyncMock(return_value=([{'job_id':1,'match_score':90}],{}))
        candidate={'id':1,'title':'测试岗位','company':'学校'}
        async def call(uid,skills):
            model=match_api.MatchRequest(resume=match_api.ResumeInfo(skills=skills),preference=match_api.MatchPreference())
            return await match_api.recommend(model,req,{'id':uid})
        with patch.object(match_api,'call_deepseek_match',ai), \
             patch.object(match_api,'pre_filter',return_value=[candidate]), \
             patch.object(match_api,'log_action'):
            self.assertFalse(asyncio.run(call(1,['Python'])).cached)
            self.assertFalse(asyncio.run(call(1,['SQL'])).cached)
            self.assertFalse(asyncio.run(call(2,['Python'])).cached)
            self.assertTrue(asyncio.run(call(1,['Python'])).cached)
        self.assertEqual(3,ai.await_count)

    def test_failed_mail_keeps_user_checkpoint_for_retry(self):
        conn=sqlite3.connect(self.db)
        conn.executescript('''CREATE TABLE users(id INTEGER,username TEXT,notify_email TEXT,is_disabled INTEGER);
            CREATE TABLE member_resumes(user_id INTEGER,resume_text TEXT,parsed_json TEXT);
            INSERT INTO users VALUES(1,'测试','test@example.org',0);
            INSERT INTO member_resumes VALUES(1,'简历','{}');''')
        conn.commit();conn.close()
        old='2026-01-01 00:00:00'
        scheduler.save_sub_config({'enabled':True,'last_run':old})
        def candidates(**kwargs):
            return [{'id':1,'title':'信息管理','company':'学校'}] if kwargs['job_type']=='社招' else []
        with patch.object(match_db,'pre_filter',side_effect=candidates) as pre, \
             patch.object(scheduler,'_send_email',side_effect=[(False,'SMTP test failure'),(True,'ok')]):
            self.assertFalse(scheduler.run_subscription_scan()['success'])
            self.assertEqual(old,scheduler.load_sub_config()['user_last_run']['1'])
            self.assertTrue(scheduler.run_subscription_scan()['success'])
            self.assertNotEqual(old,scheduler.load_sub_config()['user_last_run']['1'])
            self.assertTrue(all(c.kwargs['updated_after']==old for c in pre.call_args_list))

    def test_long_multibyte_password_returns_validation_error_before_database_access(self):
        import auth
        result=auth.register_user('测试用户','密'*25)
        self.assertFalse(result['ok'])
        self.assertIn('72',result['message'])
        with self.assertRaises(match_api.HTTPException) as caught:
            asyncio.run(match_api.change_password(match_api.ChangePasswordRequest(
                old_password='old',new_password='密'*25),{'id':1}))
        self.assertEqual(400,caught.exception.status_code)

    def test_new_database_has_no_fixed_admin_password(self):
        import db_schema_v2,auth
        db_schema_v2.upgrade_schema(str(self.db))
        conn=sqlite3.connect(self.db)
        hashed=conn.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
        conn.close()
        self.assertFalse(auth.verify_password('admin123',hashed))

    def test_uninitialized_background_start_requires_setup(self):
        import serve
        with patch.object(serve,'BASE_DIR',str(self.root)),patch.object(serve,'BACKGROUND',True):
            with self.assertRaises(SystemExit) as caught:serve.ensure_initialized()
        self.assertEqual(1,caught.exception.code)

    def test_seed_export_excludes_private_tables_and_cache(self):
        import build_portable
        conn=sqlite3.connect(self.db)
        conn.executescript("CREATE TABLE users(id INTEGER,password_hash TEXT); INSERT INTO users VALUES(1,'private');")
        conn.execute("INSERT INTO jobs(title,company) VALUES('公开岗位','学校')")
        conn.execute("INSERT INTO match_cache(resume_hash,preference_hash,result_json) VALUES('private','private','private')")
        conn.commit();conn.close()
        destination=self.root/'seed.db'
        build_portable.export_seed_jobs(str(self.db),str(destination))
        conn=sqlite3.connect(destination)
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('users',tables)
        self.assertEqual(0,conn.execute('SELECT count(*) FROM match_cache').fetchone()[0])
        self.assertEqual('公开岗位',conn.execute('SELECT title FROM jobs').fetchone()[0]);conn.close()

    def test_cached_package_secrets_are_removed_before_rebuild(self):
        import build_portable
        package=self.root/'package';(package/'data').mkdir(parents=True);(package/'cookies').mkdir()
        (package/'data'/'.initialized').write_text('old')
        (package/'cookies'/'51job.json').write_text('private')
        (package/'.env.match').write_text('private')
        build_portable.clean_package_private_data(str(package))
        self.assertEqual([],list((package/'data').iterdir()))
        self.assertEqual([],list((package/'cookies').iterdir()))
        self.assertFalse((package/'.env.match').exists())

if __name__=='__main__':unittest.main()
