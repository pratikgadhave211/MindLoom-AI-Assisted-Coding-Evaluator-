from pathlib import Path

root = Path(__file__).parent / 'code-server'
targets = set()
for patch in (root / 'patches').glob('*.diff'):
    for line in patch.read_bytes().splitlines():
        if line.startswith(b'+++ code-server/'):
            targets.add(root / line[len(b'+++ code-server/'):].split(b'\t', 1)[0].decode('utf-8'))
for path in targets:
    if path.is_file():
        data = path.read_bytes()
        path.write_bytes(data.replace(b'\r\n', b'\n'))
print(f'Checked {len(targets)} upstream patch targets')
scripts = 0
for path in root.rglob('*.sh'):
    if any(part in {'.git', 'node_modules', '.pc'} for part in path.parts):
        continue
    data = path.read_bytes()
    if b'\r\n' in data:
        path.write_bytes(data.replace(b'\r\n', b'\n'))
        scripts += 1
print(f'Normalized {scripts} shell scripts')
