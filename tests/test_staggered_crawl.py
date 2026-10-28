import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import scheduler


class StaggeredCrawlTests(unittest.TestCase):
    def test_one_keyword_rotates_and_cooldown_survives_failure(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(scheduler, 'CONFIG_FILE', str(Path(folder)/'config.json')), \
             patch.object(scheduler, 'LOG_DIR', folder), \
             patch.object(scheduler, 'social_running', False), \
             patch.object(scheduler, '_run_crawler_subprocess', return_value=1) as run, \
             patch.object(scheduler, '_sync_db', return_value=2), \
             patch.object(scheduler.time, 'time', return_value=100000):
            scheduler.save_crawl_config(dict(keywords=['A','B','C','D','E'], interval_hours=48))
            self.assertFalse(scheduler.run_social_crawl()['success'])
            args = run.call_args.args[0]
            self.assertEqual('A', args[args.index('--keywords')+1])
            self.assertEqual('50', args[args.index('--max-pages')+1])
            self.assertFalse(scheduler.run_social_crawl()['success'])
            self.assertEqual(1, run.call_count)
            cfg = scheduler.load_crawl_config()
            self.assertEqual(1, cfg['batch_cursor'])
            with patch.object(scheduler.time, 'time', return_value=134560):
                self.assertEqual(['B'], scheduler.social_batch_plan(cfg)[0])

    def test_restart_and_changed_keywords_respect_saved_cooldown(self):
        cfg = dict(keywords=['X'], interval_hours=1, batch_cursor=9, batch_last_attempt=100000)
        with patch.object(scheduler.time, 'time', return_value=100001):
            self.assertEqual([], scheduler.social_batch_plan(cfg)[0])
        with patch.object(scheduler.time, 'time', return_value=103600):
            self.assertEqual(['X'], scheduler.social_batch_plan(cfg)[0])
