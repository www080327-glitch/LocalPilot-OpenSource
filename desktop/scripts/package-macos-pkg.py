"""Package a verified APP for the current user's Applications folder.

No installer scripts, privilege escalation, model download, service changes,
or security exceptions. The system Installer owns the actual installation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import xml.etree.ElementTree as ET


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--stage', type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve(strict=True)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'io.localpilot.desktop':
        raise ValueError('Only the production-identity APP may be packaged')
    version = info['CFBundleShortVersionString']
    if version != '5.0.1-rc.7':
        raise ValueError('This installer recipe is pinned to RC.7')
    if args.stage.exists() or args.out.exists():
        raise FileExistsError('Existing installer or staging must be retained')
    args.stage.mkdir(mode=0o700, parents=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    run('codesign', '--verify', '--deep', '--strict', app)
    payload = args.stage / 'payload'
    target = payload / 'Applications/LocalPilot.app'
    target.parent.mkdir(parents=True)
    run('ditto', '--norsrc', '--noextattr', app, target)
    run('codesign', '--verify', '--deep', '--strict', target)
    components = args.stage / 'components.plist'
    run('pkgbuild', '--analyze', '--root', payload, components)
    specs = plistlib.loads(components.read_bytes())
    if len(specs) != 1 or specs[0]['RootRelativeBundlePath'] != 'Applications/LocalPilot.app':
        raise ValueError('Unexpected executable bundle in installer payload')
    specs[0].update(BundleIsRelocatable=False, BundleIsVersionChecked=True,
                    BundleHasStrictIdentifier=True, BundleOverwriteAction='upgrade')
    components.write_bytes(plistlib.dumps(specs))
    component = args.stage / 'LocalPilot.component.pkg'
    run('pkgbuild', '--root', payload, '--component-plist', components,
        '--identifier', 'io.localpilot.desktop.pkg', '--version', '5.0.1.7',
        '--install-location', '/', '--ownership', 'recommended', component)
    resources = args.stage / 'Resources'
    resources.mkdir()
    welcome = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<body style="font:16px -apple-system;line-height:1.6"><h1>安装 LocalPilot RC.7</h1>
<p>安装器会把 LocalPilot 放进你的个人“应用程序”文件夹，无需拖拽文件。</p>
<p>已内置 Python、Core、Suite、Companion 和 Channels。首次打开后，按向导选择模型或配置云端 API；模型权重另行下载或选择已有文件。</p>
<p>安装前请退出正在运行的 LocalPilot。已有用户请先保留旧版本和状态备份。</p>
<p><strong>这是未公证的个人工程候选。</strong>macOS 可能要求你在“系统设置 → 隐私与安全性”中手动允许。安装器不会关闭系统保护。</p>
<p>需要 Apple Silicon 和 macOS 15 或更新版本。</p></body></html>'''
    conclusion = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<body style="font:16px -apple-system;line-height:1.6"><h1>应用文件已安装</h1>
<p>从个人“应用程序”文件夹打开 LocalPilot，完成首次设置。</p>
<p>首次初始化可能需要约两分钟。模型下载、云端 API、文件授权和 QQ／微信登录仍由你在向导中确认。</p>
<p>此安装器不恢复旧的用户状态，也不自动提交 Agent 任务。</p></body></html>'''
    (resources / 'Welcome.html').write_text(welcome)
    (resources / 'Conclusion.html').write_text(conclusion)
    distribution = ET.Element('installer-gui-script', {'minSpecVersion': '2'})
    ET.SubElement(distribution, 'title').text = 'LocalPilot 5.0.1-rc.7'
    ET.SubElement(distribution, 'welcome', {'file': 'Welcome.html', 'mime-type': 'text/html'})
    ET.SubElement(distribution, 'conclusion', {'file': 'Conclusion.html', 'mime-type': 'text/html'})
    ET.SubElement(distribution, 'domains', {'enable_anywhere': 'false',
                  'enable_currentUserHome': 'true', 'enable_localSystem': 'false'})
    ET.SubElement(distribution, 'options', {'customize': 'never',
                  'require-scripts': 'false', 'hostArchitectures': 'arm64'})
    outline = ET.SubElement(distribution, 'choices-outline')
    ET.SubElement(outline, 'line', {'choice': 'localpilot'})
    choice = ET.SubElement(distribution, 'choice', {'id': 'localpilot', 'visible': 'false'})
    ET.SubElement(choice, 'pkg-ref', {'id': 'io.localpilot.desktop.pkg'})
    ET.SubElement(distribution, 'pkg-ref', {'id': 'io.localpilot.desktop.pkg',
                  'version': '5.0.1.7', 'auth': 'none'}).text = component.name
    close_ref = ET.SubElement(distribution, 'pkg-ref', {'id': 'io.localpilot.desktop.pkg'})
    ET.SubElement(ET.SubElement(close_ref, 'must-close'), 'app', {'id': 'io.localpilot.desktop'})
    xml = args.stage / 'Distribution.xml'
    ET.indent(distribution)
    ET.ElementTree(distribution).write(xml, encoding='utf-8', xml_declaration=True)
    run('productbuild', '--distribution', xml, '--resources', resources,
        '--package-path', args.stage, args.out)
    with args.out.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    print(json.dumps({'installer': args.out.name, 'bytes': args.out.stat().st_size,
                      'sha256': digest, 'version': version, 'destination': '~/Applications/LocalPilot.app',
                      'domain': 'CurrentUserHome', 'installer_scripts': False,
                      'notarized': False, 'actual_installation': 'NOT_RUN'}))


if __name__ == '__main__':
    main()
