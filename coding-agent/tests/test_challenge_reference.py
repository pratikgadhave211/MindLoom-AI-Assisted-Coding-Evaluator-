import shutil
import subprocess
import sys
from pathlib import Path


def test_reference_solution_passes_visible_and_regression_tests(tmp_path):
    root = Path(__file__).resolve().parents[2]
    template = root / 'broken-repos/flaskr-secure-search'
    reference = root / 'coding-agent/challenges/flaskr-secure-search/reference.patch'
    work = tmp_path / 'challenge'
    shutil.copytree(template, work, ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '*.pyc'))
    subprocess.run(['git', 'apply', str(reference)], cwd=work, check=True, capture_output=True)
    shutil.copy(root / 'coding-agent/challenges/flaskr-secure-search/author_checks.py', work / 'tests/test_author_checks.py')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=work, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_alternative_authorization_implementation_passes(tmp_path):
    root = Path(__file__).resolve().parents[2]
    work = tmp_path / 'challenge'
    shutil.copytree(root / 'broken-repos/flaskr-secure-search', work,
                    ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '*.pyc'))
    reference = root / 'coding-agent/challenges/flaskr-secure-search/reference.patch'
    subprocess.run(['git', 'apply', str(reference)], cwd=work, check=True, capture_output=True)
    blog = work / 'flaskr/blog.py'
    text = blog.read_text(encoding='utf-8')
    text = text.replace('    post = get_post(id, check_author=True)\n',
                        '    post = get_post(id)\n    if post["author_id"] != g.user["id"]:\n        abort(403)\n')
    text = text.replace('    get_post(id, check_author=True)\n',
                        '    post = get_post(id)\n    if post["author_id"] != g.user["id"]:\n        abort(403)\n')
    blog.write_text(text, encoding='utf-8')
    shutil.copy(root / 'coding-agent/challenges/flaskr-secure-search/author_checks.py', work / 'tests/test_author_checks.py')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=work, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
