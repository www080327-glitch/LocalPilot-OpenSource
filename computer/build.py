"""Build first-party Swift AX helper and disposable fixture, without installing anything."""
import argparse
import hashlib
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
# Build outside Desktop so Finder cannot race signing by adding .app metadata.
# Each checkout has a separate cache; no third-party bundles are modified.
BUILD = Path.home() / "Library" / "Caches" / "LocalPilotAX" / hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
FIXTURE_ID = "org.localpilot.axfixture"


def build(fixture_id=FIXTURE_ID):
    if sys.platform != "darwin":
        raise RuntimeError("Native Computer Use Alpha requires macOS.")
    BUILD.mkdir(parents=True, exist_ok=True)
    bridge = BUILD / "axbridge"
    fixture = BUILD / ("LocalPilot AX Fixture.app" if fixture_id == FIXTURE_ID else "LocalPilot AX Fixture 2.app") / "Contents"
    (fixture / "MacOS").mkdir(parents=True, exist_ok=True)
    for source, output in (("AXBridge.swift", bridge), ("AXFixture.swift", fixture / "MacOS" / "AXFixture")):
        subprocess.run(["swiftc", str(ROOT / "native" / source), "-o", str(output)], check=True)
    (fixture / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": fixture_id,
        "CFBundleName": "LocalPilot AX Fixture", "CFBundleExecutable": "AXFixture",
        "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "LSUIElement": True}))
    # Finder may attach these to a newly generated .app on Desktop. Clean only
    # our own build output before signing; never alter third-party app signatures.
    subprocess.run(["xattr", "-cr", str(fixture.parent)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(fixture.parent)], check=True)
    return bridge, fixture.parent


def build_local_native():
    """Compile an isolated experimental helper; never replace the stable AX binary."""
    if sys.platform != "darwin":
        raise RuntimeError("LocalNativeBackend requires macOS")
    BUILD.mkdir(parents=True, exist_ok=True)
    output = BUILD / "localnativebridge"
    with tempfile.TemporaryDirectory(prefix="localpilot-native-build-") as directory:
        main = Path(directory) / "main.swift"
        main.write_text((ROOT / "native" / "AXBridge.swift").read_text())
        subprocess.run(["swiftc", "-D", "LOCAL_NATIVE", str(main),
                        str(ROOT / "native" / "LocalNativeInput.swift"), "-o", str(output)], check=True)
    return output


def build_computer_use():
    """Separate helper; no installation, TCC prompts, or stable binary replacement."""
    if sys.platform != "darwin":
        raise RuntimeError("Computer Use requires macOS")
    BUILD.mkdir(parents=True, exist_ok=True)
    output = BUILD / "computerusebridge"
    with tempfile.TemporaryDirectory(prefix="localpilot-computer-build-") as directory:
        main = Path(directory) / "main.swift"
        main.write_text((ROOT / "native" / "AXBridge.swift").read_text())
        subprocess.run(["swiftc", "-D", "COMPUTER_USE", str(main),
                        str(ROOT / "native" / "ComputerUse.swift"), "-o", str(output)], check=True)
    return output


def build_window_vision():
    """Read-only on-device OCR/diff helper; launches no app and installs nothing."""
    BUILD.mkdir(parents=True, exist_ok=True)
    output=BUILD/'windowvision'
    subprocess.run(['swiftc',str(ROOT/'native'/'WindowVision.swift'),'-o',str(output)],check=True)
    return output


def build_computer_fixture():
    """One reusable, separately identified generated-data fixture, never LocalPilot.app."""
    BUILD.mkdir(parents=True, exist_ok=True)
    fixture = BUILD / "LocalPilot Computer Fixture.app" / "Contents"
    (fixture / "MacOS").mkdir(parents=True, exist_ok=True)
    subprocess.run(["swiftc", str(ROOT / "native" / "ComputerFixture.swift"),
                    "-o", str(fixture / "MacOS" / "ComputerFixture")], check=True)
    (fixture / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier":"org.localpilot.computerfixture",
        "CFBundleName":"LocalPilot Computer Fixture", "CFBundleExecutable":"ComputerFixture",
        "CFBundlePackageType":"APPL", "CFBundleVersion":"1"}))
    subprocess.run(["xattr", "-cr", str(fixture.parent)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(fixture.parent)], check=True)
    return fixture.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-fixture", action="store_true")
    parser.add_argument("--second-fixture", action="store_true", help="Build a second disposable app for different-app concurrency research")
    parser.add_argument("--experimental-native", action="store_true", help="Build only the experimental keyboard helper; launches no app")
    parser.add_argument("--computer-use", action="store_true", help="Build only the default-off scoped Computer Use helper")
    parser.add_argument("--computer-fixture", action="store_true", help="Build the one isolated Computer Use test app")
    parser.add_argument("--window-vision", action="store_true", help="Build local read-only OCR/difference helper")
    args = parser.parse_args()
    if args.computer_use or args.computer_fixture or args.window_vision:
        if args.computer_use: print(build_computer_use())
        if args.window_vision: print(build_window_vision())
        if args.computer_fixture: print(build_computer_fixture())
        return
    if args.experimental_native:
        print(build_local_native())
        return
    bridge, fixture = build(FIXTURE_ID + ".second" if args.second_fixture else FIXTURE_ID)
    print(f"AX helper: {bridge}\nTest app: {fixture}")
    if args.launch_fixture:
        subprocess.run(["open", "-g", str(fixture)], check=True)


if __name__ == "__main__":
    main()
