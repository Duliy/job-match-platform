import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import import_data
import match_db
from job_regions import job_province


class JobSearchTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        db=str(Path(self.folder.name)/'jobs.db')
        self.mock=patch.object(match_db,'DB_PATH',db)
        self.mock.start();self.addCleanup(self.mock.stop)
        conn=sqlite3.connect(db);import_data.create_tables(conn)
        conn.executemany('INSERT INTO jobs(title,company,city,location,keywords,education,salary_max) VALUES(?,?,?,?,?,?,?)',[
            ('数据分析师','甲公司','成都','四川省成都市高新区','信息管理','本科',10000),
            ('数据分析师','乙公司','绵阳','绵阳市','大数据','硕士',12000),
            ('营销经理','丙公司','成都','成都','市场营销','本科',15000),
            ('数据分析师','丁公司','深圳','广东省深圳市','大数据','本科',14000),
            ('100%_分析师','测试公司','重庆','重庆市渝北区','信息管理','本科',9000),
        ])
        conn.execute("INSERT INTO gk_jobs(title,company,department,province,region,major_req) VALUES('数据管理岗','某局','办公室','四川省','成都市','信息管理')")
        conn.commit();conn.close()

    def test_province_options_group_cities_and_filter_all_matching_cities(self):
        self.assertEqual(['四川','广东','重庆'],match_db.get_all_provinces())
        rows,total=match_db.query_jobs(city='四川省')
        self.assertEqual(3,total)
        self.assertEqual({'成都','绵阳'}, {r['city'] for r in rows})
        self.assertEqual(2,match_db.query_jobs(city='成都')[1])

    def test_city_and_multiple_terms_match_across_fields_with_and_semantics(self):
        self.assertEqual(1,match_db.query_jobs(keyword='  成都　数据\t分析师 ')[1])
        self.assertEqual(2,match_db.query_jobs(keyword='四川 数据分析师')[1])
        self.assertEqual(0,match_db.query_jobs(keyword='成都 深圳')[1])
        self.assertEqual(1,match_db.query_jobs(keyword='成都 甲公司', city='四川')[1])
        self.assertEqual(0,match_db.query_jobs(keyword='成都 数据分析师', city='广东')[1])
        self.assertEqual(1,match_db.query_jobs(keyword='%_')[1])
        self.assertEqual(5,match_db.query_jobs(keyword='   ')[1])

    def test_gk_supports_province_and_city_terms(self):
        self.assertEqual(['四川'],match_db.get_all_provinces('公考'))
        self.assertEqual(1,match_db.query_gk_jobs(keyword='成都 数据',province='四川')[1])
        self.assertEqual(0,match_db.query_gk_jobs(keyword='深圳 数据')[1])
        self.assertEqual(1,match_db.query_gk_jobs(keyword='信息管理 某局')[1])

    def test_location_normalization_and_unknown_data(self):
        for city,location,expected in [('广州','','广东'),('乌鲁木齐','','新疆'),
                ('呼和浩特','','内蒙古'),('','',''),('全国','',''),
                ('未知','四川省成都市','四川'),('海南藏族自治州','','青海'),
                ('重庆市渝北区','','重庆'),('北京市','','北京')]:
            self.assertEqual(expected,job_province(city,location),(city,location))
