"""Build only the email-first public site; never publish the future portal."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = ("index.html", "style.css", "guide.html", "guide.css", "privacy.html", "404.html", "favicon.svg", "_headers")


def main():
    output = ROOT / "dist" / "site"
    if (ROOT / "dist").is_symlink() or output.is_symlink():
        raise SystemExit("Public output must not be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    unexpected = [path for path in output.iterdir() if path.name not in PUBLIC_FILES]
    if unexpected:
        raise SystemExit("Unexpected files in public output; refusing deployment packaging")
    for name in PUBLIC_FILES:
        source = ROOT / "docs" / name
        if source.is_symlink() or (output / name).is_symlink():
            raise SystemExit("Public files must not be symlinks")
        shutil.copyfile(source, output / name)
    print(output)


if __name__ == "__main__":
    main()
