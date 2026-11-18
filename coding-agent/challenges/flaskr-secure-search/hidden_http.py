"""Run inside a separate test container. Never mount this file into the candidate."""
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request

base = 'http://candidate:5000'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def session():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                       urllib.request.ProxyHandler({}), NoRedirect())


def request(client, path, data=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        with client.open(base + path, body, timeout=5) as response:
            return response.status, response.read(1024 * 1024).decode('utf-8', errors='replace'), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, '', dict(error.headers)


alice, bob, guest = session(), session(), session()
ready = False
for _ in range(30):
    try:
        request(guest, '/')
        ready = True
        break
    except (OSError, urllib.error.URLError):
        time.sleep(0.5)
if not ready:
    print(json.dumps({'status': 'could_not_evaluate', 'reason': 'Challenge application did not start.'}))
    raise SystemExit(0)

try:
    for client, user in [(alice, 'assessment_alice'), (bob, 'assessment_bob')]:
        request(client, '/auth/register', {'username': user, 'password': 'example-password'})
        request(client, '/auth/login', {'username': user, 'password': 'example-password'})
    for index in range(7):
        request(alice, '/create', {'title': f'Needle item {index}', 'body': f'body marker {index}'})
    request(alice, '/create', {'title': 'Literal % under_score', 'body': 'uniquebodyword'})
    request(alice, '/create', {'title': "Quote ' only", 'body': 'sample'})
    request(alice, '/create', {'title': 'CAFÉ notes', 'body': 'sample'})

    results = []
    def check(name, passed):
        results.append({'name': name, 'status': 'passed' if passed else 'failed'})

    check('Other users cannot update or delete a post',
          request(bob, '/1/update', {'title': 'bad', 'body': ''})[0] == 403 and
          request(bob, '/1/delete', {})[0] == 403)
    update = request(alice, '/1/update', {'title': 'Needle updated', 'body': 'body marker 0'})
    check('Authors can update their own posts', update[0] == 302 and 'Needle updated' in request(alice, '/1/update')[1])
    guest_update = request(guest, '/1/update', {'title': 'bad', 'body': ''})
    guest_delete = request(guest, '/1/delete', {})
    check('Logged-out users cannot manage posts', guest_update[0] == 302 and guest_delete[0] == 302 and
          guest_update[2].get('Location', '').startswith('/auth/login') and guest_delete[2].get('Location', '').startswith('/auth/login'))
    first = request(guest, '/?q=++NeEdLe++&page=1')
    second = request(guest, '/?q=needle&page=2')
    check('Search and pagination return matching posts', first[0] == 200 and second[0] == 200 and
          first[1].count('<article class="post">') == 5 and second[1].count('<article class="post">') == 2)
    check('Results use stable newest-first ordering', 'Needle item 6' in first[1] and
          'Needle item 1' not in first[1] and 'Needle item 1' in second[1])
    check('Navigation preserves the search query', 'page=2' in first[1] and 'q=NeEdLe' in first[1])
    search_body = request(guest, '/?q=uniquebodyword')
    literal = request(guest, '/?q=%25')
    underscore = request(guest, '/?q=%5F')
    quote = request(guest, '/?q=%27')
    check('Search includes bodies and treats special characters literally',
          'Literal % under_score' in search_body[1] and 'Literal % under_score' in literal[1] and
          'Needle item' not in literal[1] and 'Literal % under_score' in underscore[1] and
          'Needle item' not in underscore[1] and 'Quote &#39; only' in quote[1])
    unicode_search = request(guest, '/?q=' + urllib.parse.quote('café'))
    check('Search matches Unicode case-insensitively', 'CAFÉ notes' in unicode_search[1] and 'Needle item' not in unicode_search[1])
    check('Invalid and out-of-range pages return 404', all(request(guest, '/?page=' + value)[0] == 404 for value in ('0', 'bad', '99')))
    check('Empty search results are a valid first page', request(guest, '/?q=unmatchedvalue&page=1')[0] == 200 and
          request(guest, '/?q=unmatchedvalue&page=2')[0] == 404)
    check('Authors can delete their own posts', request(alice, '/8/delete', {})[0] == 302 and request(alice, '/8/update')[0] == 404)
    print(json.dumps({'status': 'completed', 'behaviors': results}))
except Exception:
    print(json.dumps({'status': 'could_not_evaluate', 'reason': 'The behavior checks could not complete.'}))
