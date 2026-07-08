#!/usr/bin/env python3
"""config.py 的回归测试：路径配置、课程映射、image_dir_for 兜底。"""
from pathlib import Path

import pytest

from config import (
    COURSES,
    COURSE_BY_KEY,
    COURSE_BY_OUT_JSON,
    PROJECT_ROOT,
    image_dir_for,
)


class TestConfig:
    def test_project_root_is_repo_root(self):
        # PROJECT_ROOT 应该是 tests/ 的父目录
        assert (PROJECT_ROOT / 'tests' / 'conftest.py').exists()
        assert (PROJECT_ROOT / 'scripts' / 'config.py').exists()

    def test_four_courses(self):
        assert [c.key for c in COURSES] == ['ds', 'coa', 'net', 'os']
        assert {c.name for c in COURSES} == {'数据结构', '计算机组成原理', '计算机网络', '操作系统'}

    def test_course_paths_are_absolute(self):
        for c in COURSES:
            assert c.out_json.is_absolute()
            assert c.ocr_dir.is_absolute()
            assert c.qa_json.is_absolute()
            assert c.toc_json.is_absolute()
            assert c.pdf_images_dir.is_absolute()

    def test_image_dir_for(self):
        assert image_dir_for('output/questions.json').name == 'ds'
        assert image_dir_for('output/questions_coa.json').name == 'coa'
        assert image_dir_for('output/questions_net.json').name == 'net'
        assert image_dir_for('output/questions_os.json').name == 'os'

    def test_course_by_out_json(self):
        assert COURSE_BY_OUT_JSON['questions.json'].key == 'ds'
        assert COURSE_BY_OUT_JSON['questions_coa.json'].key == 'coa'

    def test_course_by_key(self):
        assert COURSE_BY_KEY['ds'].name == '数据结构'
        assert COURSE_BY_KEY['os'].pdf_images_dir.name == 'os'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
