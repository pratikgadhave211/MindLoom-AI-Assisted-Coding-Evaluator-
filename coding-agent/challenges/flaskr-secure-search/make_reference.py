from difflib import unified_diff
from pathlib import Path

root = Path(__file__).resolve().parents[3] / 'broken-repos' / 'flaskr-secure-search'
blog_path = root / 'flaskr/blog.py'
html_path = root / 'flaskr/templates/blog/index.html'
original_blog = blog_path.read_text(encoding='utf-8')
original_html = html_path.read_text(encoding='utf-8')
start = original_blog.index('    db = get_db()\n', original_blog.index('def index():'))
end = original_blog.index('\n\n\ndef get_post', start)
new_index = '''    db = get_db()
    query = request.args.get("q", "").strip()
    page_text = request.args.get("page", "1")
    if not page_text.isascii() or not page_text.isdecimal() or int(page_text) < 1:
        abort(404)
    page = int(page_text)
    posts = db.execute(
        "SELECT p.id, title, body, created, author_id, username"
        " FROM post p JOIN user u ON p.author_id = u.id"
        " ORDER BY created DESC, p.id DESC"
    ).fetchall()
    if query:
        search = query.casefold()
        posts = [post for post in posts if search in post["title"].casefold() or search in post["body"].casefold()]
    count = len(posts)
    if page > max(1, (count + 4) // 5):
        abort(404)
    posts = posts[(page - 1) * 5:page * 5]
    return render_template("blog/index.html", posts=posts, q=query, page=page, has_next=page * 5 < count)
'''
new_blog = original_blog[:start] + new_index.rstrip() + original_blog[end:]
new_blog = new_blog.replace('    post = get_post(id)\n', '    post = get_post(id, check_author=True)\n')
new_blog = new_blog.replace('    get_post(id)\n', '    get_post(id, check_author=True)\n')
new_html = original_html.replace('  {% for post in posts %}', '''  <form method="get">
    <label for="q">Search posts</label>
    <input id="q" name="q" value="{{ q }}">
    <button type="submit">Search</button>
  </form>
  {% for post in posts %}''').replace('{% endblock %}\n', '''  {% if page > 1 %}<a href="{{ url_for('blog.index', q=q, page=page-1) }}">Previous</a>{% endif %}
  {% if has_next %}<a href="{{ url_for('blog.index', q=q, page=page+1) }}">Next</a>{% endif %}
{% endblock %}
''', 1)
parts = []
for path, before, after in [('flaskr/blog.py', original_blog, new_blog), ('flaskr/templates/blog/index.html', original_html, new_html)]:
    parts.extend(unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/' + path, tofile='b/' + path))
(Path(__file__).parent / 'reference.patch').write_text(''.join(parts), encoding='utf-8')
